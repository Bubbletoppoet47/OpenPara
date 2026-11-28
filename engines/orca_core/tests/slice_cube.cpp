// slice_cube: the smallest possible use of the engine, to show that it links and slices.
//
//   orca_core_slice_cube <out.gcode> [size_mm=20] [key=value ...]
//
// Builds a cube, applies Orca's default full print configuration (plus any key=value given), slices, writes G-code,
// and prints a few numbers that a parity test can compare with Orca's own program (same cube, same settings).
// The steps are the ones Orca's own tests use (tests/fff_print/test_helpers.cpp: init_print and gcode).
#include <libslic3r/libslic3r.h>
#include <libslic3r/Model.hpp>
#include <libslic3r/Print.hpp>
#include <libslic3r/PrintConfig.hpp>
#include <libslic3r/TriangleMesh.hpp>
#include <libslic3r/GCode/GCodeProcessor.hpp>
#include <libslic3r/Utils.hpp>

#include <cstdlib>
#include <iostream>
#include <string>

using namespace Slic3r;

int main(int argc, char **argv)
{
    const std::string out  = argc > 1 ? argv[1] : "cube.gcode";
    const double      size = argc > 2 ? std::atof(argv[2]) : 20.0;

    DynamicPrintConfig config = DynamicPrintConfig::full_print_config();
    config.set_key_value("gcode_comments", new ConfigOptionBool(true));
    for (int i = 3; i < argc; ++i) {
        const std::string kv = argv[i];
        const auto        eq = kv.find('=');
        if (eq == std::string::npos) { std::cerr << "expected key=value: " << kv << "\n"; return 2; }
        ConfigSubstitutionContext ctx(ForwardCompatibilitySubstitutionRule::Disable);
        if (!config.set_deserialize_nothrow(kv.substr(0, eq), kv.substr(eq + 1), ctx)) { std::cerr << "bad setting: " << kv << "\n"; return 2; }
    }

    Model        model;
    ModelObject *object = model.add_object();
    object->name        = "cube.stl";
    object->add_volume(TriangleMesh(its_make_cube(size, size, size)));
    ModelInstance *inst = object->add_instance();
    inst->set_offset(Vec3d(100., 100., 0.));
    object->ensure_on_bed();

    Print print;
    print.auto_assign_extruders(object);
    print.apply(model, config);
    const StringObjectException err = print.validate();
    if (!err.string.empty()) { std::cerr << "invalid: " << err.string << "\n"; return 3; }
    print.set_status_silent();
    print.process();

    GCodeProcessorResult result;
    print.export_gcode(out, &result, nullptr);

    size_t layers = 0;
    for (const PrintObject *po : print.objects()) layers += po->layer_count();
    std::cout << "layers " << layers << "\n"
              << "moves " << result.moves.size() << "\n"
              << "gcode " << out << "\n";
    return 0;
}
