// slice_3mf: slices a project file the way Orca's own command line does, for the parity test (SLC-1).
//
//   orca_core_slice_3mf <in.3mf> <out.gcode> [--settings a.json b.json ...]
//
// With --settings the project's own settings are not used: the settings come from the given preset files (resolved presets, as
// tools/resolve_presets.py writes them: machine, process, filament), applied in that order on Orca's defaults. That is the way OpenPara
// will build a configuration from a profile bundle (SLC-3), so the parity test runs it too.
//
// The input is a 3MF that Orca wrote (`orca-slicer --export-3mf`): it carries the model with its placement and the full, resolved settings
// (Metadata/project_settings.config). This program loads both with Orca's own reader, applies the settings to a Print, slices and writes
// G-code. The G-code can then be compared, line by line, with the one Orca's program wrote for the same project.
#include <libslic3r/libslic3r.h>
#include <libslic3r/Model.hpp>
#include <libslic3r/Print.hpp>
#include <libslic3r/PrintConfig.hpp>
#include <libslic3r/Format/bbs_3mf.hpp>
#include <libslic3r/Format/ProjectStrategy.hpp>
#include <libslic3r/GCode/GCodeProcessor.hpp>
#include <libslic3r/Utils.hpp>

#include <cstdlib>
#include <iostream>
#include <map>
#include <string>

using namespace Slic3r;

int main(int argc, char **argv)
{
    if (argc < 3) { std::cerr << "usage: orca_core_slice_3mf <in.3mf> <out.gcode>\n"; return 2; }
    const std::string in = argv[1], out = argv[2];
    // resources: Orca reads a few small tables (nozzle_info.json and others) from its resources folder; ORCA_CORE_RESOURCES names it
    if (const char *res = std::getenv("ORCA_CORE_RESOURCES")) set_resources_dir(res);

    DynamicPrintConfig        config;
    ConfigSubstitutionContext substitutions(ForwardCompatibilitySubstitutionRule::EnableSilent);
    Model                     model;
    PlateDataPtrs             plates;
    std::vector<Preset *>     project_presets;
    bool                      is_bbl = false, is_orca = false;
    Semver                    file_version;
    if (!load_bbs_3mf(in.c_str(), &config, &substitutions, &model, &plates, &project_presets, &is_bbl, &is_orca, &file_version, nullptr,
                      LoadStrategy::LoadModel | LoadStrategy::LoadConfig)) {
        std::cerr << "cannot read " << in << "\n";
        return 3;
    }
    std::cout << "objects " << model.objects.size() << " plates " << plates.size() << " orca_3mf " << is_orca << "\n";

    // the defaults first, then the project's settings on top, as the command line does (the file holds every key, so this only fills what an
    // older file lacks)
    DynamicPrintConfig full = DynamicPrintConfig::full_print_config();
    if (argc > 3 && std::string(argv[3]) == "--settings") {
        for (int i = 4; i < argc; ++i) {
            std::map<std::string, std::string> key_values;
            std::string                        reason;
            ConfigSubstitutionContext          ctx(ForwardCompatibilitySubstitutionRule::EnableSilent);
            if (full.load_from_json(argv[i], ctx, false, key_values, reason) != 0) {
                std::cerr << "cannot read settings " << argv[i] << ": " << reason << "\n";
                return 5;
            }
        }
    } else
        full.apply(config, true);

    // what OrcaSlicer.cpp does before Print::apply (the single-extruder branch)
    std::vector<int> &filament_map = full.option<ConfigOptionInts>("filament_map", true)->values;
    const size_t      filaments    = full.option<ConfigOptionStrings>("filament_colour", true)->values.size();
    if (filament_map.size() < filaments) filament_map.resize(filaments, 1);
    for (int &m : filament_map) m = 1;

    Print print;
    print.apply(model, full);
    const StringObjectException err = print.validate();
    if (!err.string.empty()) { std::cerr << "invalid: " << err.string << "\n"; return 4; }
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
