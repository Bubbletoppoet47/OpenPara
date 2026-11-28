// _orca_core: the compiled part of the orca_core Python package (SLC-2).
//
// One function does the work of a slice, so that the Python side stays a thin layer and everything that is Orca's stays Orca's:
//
//   slice(objects, settings_file, gcode_path, threads, until, resources_dir, cancel_file, progress) -> dict
//
//   objects        list of dicts: name (str), vertices (N,3 float64), faces (M,3 int32), transform (4,4 float64),
//                  settings (dict str -> str, the object's own settings), drop_to_bed (bool)
//   settings_file  a JSON file of resolved settings: keys are Orca's option keys, values strings or lists of strings, the way Orca's preset
//                  files are written (tools/resolve_presets.py). Applied on Orca's defaults, as the parity test does.
//   gcode_path     where the G-code goes (absolute)
//   cancel_file    a path; while the file exists the slice is cancelled (checked every 50 ms by a thread of ours, so no Python is called)
//   progress       a callable (percent: float, message: str) or None
//
// It returns plain arrays and values (see build_result): the printed paths, the moves read back from the G-code by Orca's own G-code processor,
// the estimate, the warnings and the settings that were used.
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include <libslic3r/libslic3r.h>
#include <libslic3r/Model.hpp>
#include <libslic3r/Print.hpp>
#include <libslic3r/PrintConfig.hpp>
#include <libslic3r/TriangleMesh.hpp>
#include <libslic3r/GCode/GCodeProcessor.hpp>
#include <libslic3r/Utils.hpp>
#include <libslic3r/Exception.hpp>
#include <libslic3r/Geometry.hpp>

#include <boost/filesystem.hpp>
#include <tbb/global_control.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <map>
#include <string>
#include <thread>
#include <vector>

namespace py = pybind11;
using namespace Slic3r;

#ifndef ORCA_CORE_ORCA_COMMIT
#define ORCA_CORE_ORCA_COMMIT "unknown"
#endif

namespace {

// Errors the Python side turns into orca_core.errors.*; the text is "key\x1fobject\x1fmessage" so that the pieces survive the crossing.
struct ConfigErr : std::runtime_error { using std::runtime_error::runtime_error; };
struct SliceErr  : std::runtime_error { using std::runtime_error::runtime_error; };
struct CancelErr : std::runtime_error { using std::runtime_error::runtime_error; };

std::string pack_error(const std::string &key, const std::string &object, const std::string &message)
{
    return key + "\x1f" + object + "\x1f" + message;
}

template<class T> py::array_t<T> to_array(const std::vector<T> &v)
{
    py::array_t<T> a(static_cast<py::ssize_t>(v.size()));
    if (!v.empty()) std::memcpy(a.mutable_data(), v.data(), v.size() * sizeof(T));
    return a;
}

py::array_t<float> to_array_n3(const std::vector<float> &flat)
{
    py::array_t<float> a({static_cast<py::ssize_t>(flat.size() / 3), static_cast<py::ssize_t>(3)});
    if (!flat.empty()) std::memcpy(a.mutable_data(), flat.data(), flat.size() * sizeof(float));
    return a;
}

// Applies "key = value" strings to a config (object settings, overrides): bad key or value -> ConfigErr, in words.
void apply_strings(ConfigBase &config, const std::map<std::string, std::string> &kv, const std::string &object)
{
    for (const auto &p : kv) {
        ConfigSubstitutionContext ctx(ForwardCompatibilitySubstitutionRule::Disable);
        if (!config.set_deserialize_nothrow(p.first, p.second, ctx))
            throw ConfigErr(pack_error(p.first, object, "\"" + p.second + "\" is not a value that Orca accepts for the setting \"" + p.first + "\"."));
    }
}

struct Watcher
{
    // Cancels the print when cancel_file exists. A thread of ours polls, so that no Python is called from the engine's threads.
    Watcher(Print &print, std::string file) : m_print(print), m_file(std::move(file))
    {
        if (m_file.empty()) return;
        m_thread = std::thread([this] {
            while (!m_stop.load()) {
                boost::system::error_code ec;
                if (boost::filesystem::exists(m_file, ec)) { m_cancelled = true; m_print.cancel(); return; }
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
            }
        });
    }
    ~Watcher() { m_stop = true; if (m_thread.joinable()) m_thread.join(); }
    bool cancelled() const { return m_cancelled.load(); }
    Print &m_print;
    std::string m_file;
    std::atomic<bool> m_stop{false}, m_cancelled{false};
    std::thread m_thread;
};

// the 20 roles of ExtrusionRole in the order of the enum, the numbers are what the Python side stores
inline unsigned char role_number(ExtrusionRole r) { return static_cast<unsigned char>(r); }

py::dict build_result(const Print &print, const GCodeProcessorResult &result, const DynamicPrintConfig &config, const std::string &gcode_path,
                      int threads, const std::vector<std::string> &object_names)
{
    using MV = GCodeProcessorResult::MoveVertex;
    const auto &moves = result.moves;
    const size_t n = moves.size();

    // ---- layers: the top height of each layer, from the G-code's own layer numbering
    unsigned int max_layer = 0;
    for (const MV &m : moves) max_layer = std::max(max_layer, m.layer_id);
    std::vector<float> layer_z(n ? max_layer + 1 : 0, 0.f);
    for (const MV &m : moves)
        if (m.type == EMoveType::Extrude && m.layer_id < layer_z.size()) layer_z[m.layer_id] = std::max(layer_z[m.layer_id], m.position.z());
    for (size_t i = 1; i < layer_z.size(); ++i)
        if (layer_z[i] == 0.f) layer_z[i] = layer_z[i - 1];

    // ---- paths: a run of extrusion moves that share role, width, height, flow, layer, tool and object is one path; its first point is where the
    //      nozzle was before the first move (the end of the move before it)
    std::vector<float> pts;
    std::vector<int64_t> start{0};
    std::vector<unsigned char> p_role, p_extruder;
    std::vector<float> p_width, p_height, p_flow;
    std::vector<int32_t> p_layer;
    std::vector<int16_t> p_object;
    pts.reserve(n * 3);
    auto same = [](const MV &a, const MV &b) {
        return a.extrusion_role == b.extrusion_role && a.layer_id == b.layer_id && a.extruder_id == b.extruder_id &&
               a.object_label_id == b.object_label_id && std::abs(a.width - b.width) < 1e-5f && std::abs(a.height - b.height) < 1e-5f &&
               std::abs(a.mm3_per_mm - b.mm3_per_mm) < 1e-6f;
    };
    bool open = false;
    for (size_t i = 0; i < n; ++i) {
        const MV &m = moves[i];
        const bool extrude = m.type == EMoveType::Extrude && m.mm3_per_mm > 0.f;
        if (open && !(extrude && same(moves[i - 1], m))) { start.push_back(static_cast<int64_t>(pts.size() / 3)); open = false; }
        if (!extrude) continue;
        if (!open) {
            const Vec3f &p0 = i > 0 ? moves[i - 1].position : m.position;
            pts.insert(pts.end(), {p0.x(), p0.y(), p0.z()});
            p_role.push_back(role_number(m.extrusion_role));
            p_width.push_back(m.width);
            p_height.push_back(m.height);
            p_flow.push_back(m.mm3_per_mm);
            p_layer.push_back(static_cast<int32_t>(m.layer_id));
            p_object.push_back(static_cast<int16_t>(std::max(0, m.object_label_id)));
            p_extruder.push_back(m.extruder_id);
            open = true;
        }
        pts.insert(pts.end(), {m.position.x(), m.position.y(), m.position.z()});
    }
    if (open) start.push_back(static_cast<int64_t>(pts.size() / 3));
    const size_t np = p_role.size();

    py::dict paths;
    paths["points"] = to_array_n3(pts);
    paths["start"]  = to_array(start);
    paths["layer_z"] = to_array(layer_z);
    paths["col_role"] = to_array(p_role);
    paths["col_width"] = to_array(p_width);
    paths["col_height"] = to_array(p_height);
    paths["col_mm3_per_mm"] = to_array(p_flow);
    paths["col_layer"] = to_array(p_layer);
    paths["col_object"] = to_array(p_object);
    paths["col_instance"] = to_array(std::vector<int16_t>(np, 0));
    paths["col_region"] = to_array(std::vector<int16_t>(np, 0));
    paths["col_extruder"] = to_array(std::vector<int8_t>(p_extruder.begin(), p_extruder.end()));
    std::vector<int32_t> order(np);
    for (size_t i = 0; i < np; ++i) order[i] = static_cast<int32_t>(i);
    paths["col_order"] = to_array(order);
    paths["col_overhang"] = to_array(std::vector<float>(np, 0.f));
    paths["col_curve"] = to_array(std::vector<int8_t>(np, 0));
    py::array_t<bool> zc(static_cast<py::ssize_t>(np));
    std::memset(zc.mutable_data(), 0, np * sizeof(bool));
    paths["col_z_contoured"] = zc;

    // ---- moves: every move of the G-code, as Orca's G-code processor read it back
    std::vector<float> mpos(n * 3), feed(n), mtime(n), mwidth(n), mheight(n), mflow(n), fan(n), temp(n), accel(n), dext(n);
    std::vector<unsigned char> mrole(n), mtype(n), mext(n);
    std::vector<uint32_t> mlayer(n);
    for (size_t i = 0; i < n; ++i) {
        const MV &m = moves[i];
        mpos[3 * i] = m.position.x(); mpos[3 * i + 1] = m.position.y(); mpos[3 * i + 2] = m.position.z();
        feed[i] = m.feedrate; mtime[i] = m.time[0]; mwidth[i] = m.width; mheight[i] = m.height; mflow[i] = m.mm3_per_mm;
        fan[i] = m.fan_speed; temp[i] = m.temperature; accel[i] = m.acceleration; dext[i] = m.delta_extruder;
        mrole[i] = role_number(m.extrusion_role); mtype[i] = static_cast<unsigned char>(m.type); mext[i] = m.extruder_id; mlayer[i] = m.layer_id;
    }
    py::dict mv;
    mv["position"] = to_array_n3(mpos);
    mv["role"] = to_array(mrole);
    mv["type"] = to_array(mtype);
    mv["feedrate"] = to_array(feed);
    mv["time"] = to_array(mtime);
    mv["width"] = to_array(mwidth);
    mv["height"] = to_array(mheight);
    mv["mm3_per_mm"] = to_array(mflow);
    mv["fan"] = to_array(fan);
    mv["temperature"] = to_array(temp);
    mv["acceleration"] = to_array(accel);
    mv["delta_extruder"] = to_array(dext);
    mv["extruder"] = to_array(mext);
    mv["layer"] = to_array(mlayer);

    // ---- the estimate
    py::dict est;
    const auto &stats = result.print_statistics;
    est["time_normal_s"] = stats.modes[static_cast<size_t>(PrintEstimatedStatistics::ETimeMode::Normal)].time;
    est["time_silent_s"] = stats.modes[static_cast<size_t>(PrintEstimatedStatistics::ETimeMode::Stealth)].time;
    // the plastic used, per extruder: Orca's own volume (the number its G-code header turns into mm, cm3 and g)
    std::vector<double> fil_mm, fil_mm3, fil_g;
    const auto &fd = config.option<ConfigOptionFloats>("filament_diameter")->values;
    const auto &fdens = config.option<ConfigOptionFloats>("filament_density")->values;
    for (const auto &kv : stats.total_volumes_per_extruder) {
        const double d = kv.first < fd.size() ? fd[kv.first] : 1.75;
        const double dens = kv.first < fdens.size() ? fdens[kv.first] : 1.25;
        fil_mm3.push_back(kv.second);
        fil_mm.push_back(kv.second / (M_PI * d * d / 4.0));
        fil_g.push_back(kv.second / 1000.0 * dens);
    }
    est["filament_mm"] = fil_mm;
    est["filament_mm3"] = fil_mm3;
    est["filament_g"] = fil_g;
    est["cost"] = print.print_statistics().total_cost;
    est["toolchanges"] = print.print_statistics().total_toolchanges;
    // seconds by role, from the move times: time[0] of a move is the time that move takes (checked in the tests against the total)
    py::dict by_role;
    {
        std::map<unsigned char, double> acc;
        for (size_t i = 0; i < n; ++i) acc[mrole[i]] += moves[i].time[0];
        static const char *names[] = {"Undefined", "Inner wall", "Outer wall", "Overhang wall", "Sparse infill", "Internal solid infill", "Top surface",
                                      "Bottom surface", "Ironing", "Bridge", "Internal Bridge", "Gap infill", "Skirt", "Brim", "Support",
                                      "Support interface", "Support transition", "Prime tower", "Custom", "Multiple"};
        for (const auto &kv : acc)
            if (kv.first < 20) by_role[names[kv.first]] = kv.second;
    }
    est["time_by_role_s"] = by_role;

    // ---- warnings of the G-code processor (Orca's own wording), the print's are added by the caller
    py::list warns;
    for (const auto &w : result.warnings) {
        py::dict d;
        d["level"] = w.level == 0 ? "tip" : (w.level == 1 ? "warning" : "error");
        d["message"] = w.msg;
        d["code"] = 0;
        d["params"] = w.params;
        d["object"] = "";
        warns.append(d);
    }

    // ---- the settings that were used, every key as Orca writes it
    py::dict used;
    for (const std::string &k : config.keys()) used[k.c_str()] = config.opt_serialize(k);

    py::dict record;
    record["orca_version"] = std::string(SoftFever_VERSION);
    record["orca_commit"] = std::string(ORCA_CORE_ORCA_COMMIT);
    record["threads"] = threads;
    record["settings"] = used;
    record["object_names"] = object_names;

    py::dict out;
    out["gcode"] = gcode_path;
    out["paths"] = paths;
    out["moves"] = mv;
    out["estimate"] = est;
    out["warnings"] = warns;
    out["record"] = record;
    return out;
}

py::dict slice(const py::list &objects, const std::string &settings_file, const std::string &gcode_path, int threads, const std::string &until,
               const std::string &resources_dir, const std::string &cancel_file, const py::object &progress)
{
    if (!resources_dir.empty()) set_resources_dir(resources_dir);
    tbb::global_control limit(tbb::global_control::max_allowed_parallelism, static_cast<size_t>(std::max(1, threads)));

    // ---- settings: Orca's defaults, then the file
    std::vector<std::string> setting_warnings;
    DynamicPrintConfig config = DynamicPrintConfig::full_print_config();
    {
        std::map<std::string, std::string> key_values;
        std::string                        reason;
        ConfigSubstitutionContext          ctx(ForwardCompatibilitySubstitutionRule::Enable);
        if (config.load_from_json(settings_file, ctx, false, key_values, reason) != 0)
            throw ConfigErr(pack_error("", "", "The settings could not be read: " + reason));
        // a value Orca does not accept is replaced by one it does (as Orca's own window does); say so, so that it is not silent
        for (const ConfigSubstitution &sub : ctx.substitutions)
            setting_warnings.push_back("The value \"" + sub.old_value + "\" is not valid for the setting \"" + (sub.opt_def ? sub.opt_def->opt_key : std::string()) +
                                       "\"; \"" + (sub.new_value ? sub.new_value->serialize() : std::string()) + "\" is used instead.");
    }

    // ---- the model
    Model model;
    std::vector<std::string> names;
    std::vector<ModelObject *> mos;
    size_t index = 0;
    for (const py::handle &h : objects) {
        py::dict o = py::reinterpret_borrow<py::dict>(h);
        const std::string name = o["name"].cast<std::string>();
        auto v = o["vertices"].cast<py::array_t<double, py::array::c_style | py::array::forcecast>>();
        auto f = o["faces"].cast<py::array_t<int32_t, py::array::c_style | py::array::forcecast>>();
        auto t = o["transform"].cast<py::array_t<double, py::array::c_style | py::array::forcecast>>();
        if (v.ndim() != 2 || v.shape(1) != 3 || f.ndim() != 2 || f.shape(1) != 3 || t.ndim() != 2 || t.shape(0) != 4 || t.shape(1) != 4)
            throw SliceErr(pack_error("", name, "The object has a mesh or a transform of the wrong shape."));
        indexed_triangle_set its;
        its.vertices.reserve(v.shape(0));
        for (py::ssize_t i = 0; i < v.shape(0); ++i)
            its.vertices.emplace_back(static_cast<float>(v.at(i, 0)), static_cast<float>(v.at(i, 1)), static_cast<float>(v.at(i, 2)));
        its.indices.reserve(f.shape(0));
        for (py::ssize_t i = 0; i < f.shape(0); ++i) {
            const int a = f.at(i, 0), b = f.at(i, 1), c = f.at(i, 2);
            if (a < 0 || b < 0 || c < 0 || a >= v.shape(0) || b >= v.shape(0) || c >= v.shape(0))
                throw SliceErr(pack_error("", name, "A triangle points at a vertex that does not exist."));
            its.indices.emplace_back(a, b, c);
        }
        ModelObject *mo = model.add_object();
        mo->name = name;
        mo->add_volume(TriangleMesh(std::move(its)));
        ModelInstance *inst = mo->add_instance();
        inst->loaded_id = index + 1;
        Transform3d tr = Transform3d::Identity();
        for (int r = 0; r < 4; ++r)
            for (int c = 0; c < 4; ++c) tr(r, c) = t.at(r, c);
        inst->set_transformation(Geometry::Transformation(tr));
        if (o.contains("drop_to_bed") ? o["drop_to_bed"].cast<bool>() : true) mo->ensure_on_bed();
        if (o.contains("settings")) {
            DynamicPrintConfig own;
            apply_strings(own, o["settings"].cast<std::map<std::string, std::string>>(), name);
            if (!own.empty()) mo->config.assign_config(std::move(own));
        }
        mos.push_back(mo);
        names.push_back(name);
        ++index;
    }
    if (mos.empty()) throw SliceErr(pack_error("", "", "There is nothing to slice."));

    Print print;
    for (ModelObject *mo : mos) print.auto_assign_extruders(mo);
    try {
        print.apply(model, config);
    } catch (const Slic3r::Exception &e) {
        throw ConfigErr(pack_error("", "", e.what()));
    }

    std::vector<StringObjectException> warnings;
    const StringObjectException        err = print.validate(&warnings);
    if (!err.string.empty()) throw ConfigErr(pack_error(err.opt_key, "", err.string));

    // ---- progress and cancel
    print.set_status_silent();   // nothing on the console; the callback below replaces it
    int         last_pct = -1;
    std::string last_text;
    print.set_status_callback([&](const PrintBase::SlicingStatus &s) {
        if (progress.is_none() || (s.percent == last_pct && s.text == last_text) || s.percent < 0) return;
        last_pct = s.percent;
        last_text = s.text;
        py::gil_scoped_acquire gil;
        try { progress(static_cast<double>(s.percent), s.text); } catch (py::error_already_set &) { /* a failing callback must not stop the engine */ }
    });


    GCodeProcessorResult result;
    std::string          out_path = gcode_path;
    bool                 cancelled = false;
    std::string          failure;                // what the engine said, thrown below once Python is ours again
    {
        py::gil_scoped_release release;
        Watcher watcher(print, cancel_file);
        try {
            print.process();
            if (until != "slice") print.export_gcode(out_path, &result, nullptr);
        } catch (const Slic3r::CanceledException &) {
            cancelled = true;
        } catch (const std::exception &e) {
            failure = e.what();
        }
        cancelled = cancelled || watcher.cancelled();
    }
    if (cancelled) throw CancelErr("Slicing was cancelled.");
    if (!failure.empty()) throw SliceErr(pack_error("", "", failure));

    py::dict out = build_result(print, result, config, gcode_path, threads, names);
    py::list w = out["warnings"];
    for (const std::string &text : setting_warnings) {
        py::dict d;
        d["level"] = "warning";
        d["message"] = text;
        d["code"] = 0;
        d["params"] = std::vector<std::string>{};
        d["object"] = "";
        w.append(d);
    }
    for (const StringObjectException &we : warnings) {
        py::dict d;
        d["level"] = "warning";
        d["message"] = we.string;
        d["code"] = 0;
        d["params"] = std::vector<std::string>{};
        d["object"] = "";
        w.append(d);
    }
    return out;
}

} // namespace

PYBIND11_MODULE(_orca_core, m)
{
    m.doc() = "Orca Slicer's slicing engine (cut down), see engines/orca_core/README.md";
    py::register_exception<ConfigErr>(m, "ConfigError");
    py::register_exception<SliceErr>(m, "SliceError");
    py::register_exception<CancelErr>(m, "Cancelled");
    m.def("engine_version", [] {
        py::dict d;
        d["orca_version"] = std::string(SoftFever_VERSION);
        d["orca_commit"] = std::string(ORCA_CORE_ORCA_COMMIT);
        return d;
    });
    m.def("slice", &slice, py::arg("objects"), py::arg("settings_file"), py::arg("gcode_path"), py::arg("threads") = 1, py::arg("until") = "gcode",
          py::arg("resources_dir") = "", py::arg("cancel_file") = "", py::arg("progress") = py::none());
}
