# orca_core: Orca Slicer's slicing engine (libslic3r), cut down to what slicing needs.
#
# This file builds from an Orca source tree (ORCA_SRC) that tools/prepare_orca.py has checked against ORCA_PIN and patched.
# It does not use Orca's own top-level CMakeLists.txt, so the window, the CAD kernel and the libraries only they need
# (wxWidgets, OpenCASCADE, OpenCV, assimp, Draco, OpenGL) are never looked for.
#
#   python tools/prepare_orca.py <orca checkout>          # checks the pin, applies patches/
#   cmake -S engines/orca_core -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
#         -DORCA_SRC=<orca checkout> -DORCA_EIGEN_DIR=<Eigen 5 source folder> -DORCA_CGAL_DIR=<CGAL 6.2 folder>
#   cmake --build build
#
# Orca Slicer is AGPL-3.0; so is anything built from this file. See README.md.
cmake_minimum_required(VERSION 3.20)
project(orca_core LANGUAGES C CXX)

set(ORCA_SRC "" CACHE PATH "Orca Slicer source tree: the pinned release, patched by tools/prepare_orca.py")
set(ORCA_EIGEN_DIR "" CACHE PATH "Eigen 5.x source tree (the folder that holds Eigen/); empty means find_package(Eigen3)")
set(ORCA_CGAL_DIR "" CACHE PATH "CGAL 6.2 tree (the folder that holds CGALConfig.cmake); empty means find_package(CGAL)")
option(ORCA_CORE_TESTS "Build the C++ test programs in tests/" ON)

if (NOT ORCA_SRC OR NOT EXISTS "${ORCA_SRC}/src/libslic3r/CMakeLists.txt")
    message(FATAL_ERROR "Set -DORCA_SRC=<Orca Slicer source tree>. Not found: '${ORCA_SRC}'")
endif ()

if (NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif ()
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)    # the engine goes into a Python extension, which is a shared library
set(CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake" ${CMAKE_MODULE_PATH})

# ---- the list of files, made from Orca's own list minus cuts.txt --------------------------------------------------------
find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(_sources_cmake "${CMAKE_CURRENT_BINARY_DIR}/sources.cmake")
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/gen_sources.py"
            "${ORCA_SRC}" "${CMAKE_CURRENT_SOURCE_DIR}/cuts.txt" "${_sources_cmake}" "${CMAKE_CURRENT_BINARY_DIR}/cut_report.md"
    RESULT_VARIABLE _gen_rc OUTPUT_VARIABLE _gen_out ERROR_VARIABLE _gen_err)
if (NOT _gen_rc EQUAL 0)
    message(FATAL_ERROR "gen_sources.py failed: ${_gen_err}")
endif ()
message(STATUS "orca_core sources: ${_gen_out}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/cuts.txt" "${ORCA_SRC}/src/libslic3r/CMakeLists.txt")
include("${_sources_cmake}")

# ---- the version header Orca's CMake writes -------------------------------------------------------------------------------
include("${ORCA_SRC}/version.inc")
set(SLIC3R_BUILD_ID "orca_core")
set(ORCA_CHECK_GCODE_PLACEHOLDERS "0")
configure_file("${ORCA_SRC}/src/libslic3r/libslic3r_version.h.in" "${CMAKE_CURRENT_BINARY_DIR}/libslic3r_version.h" @ONLY)

# ---- libraries from the system or a package manager (6.4 of the plan) ---------------------------------------------------
if (WIN32)
    add_definitions(-DBOOST_ALL_NO_LIB -DBOOST_USE_WINAPI_VERSION=0x602 -DBOOST_SYSTEM_USE_UTF8
                    -D_USE_MATH_DEFINES -D_CRT_SECURE_NO_WARNINGS -D_SCL_SECURE_NO_WARNINGS -DNOMINMAX)
    add_compile_options("$<$<CXX_COMPILER_ID:MSVC>:/utf-8>" "$<$<CXX_COMPILER_ID:MSVC>:/bigobj>")
else ()
    add_definitions(-DBOOST_LOG_DYN_LINK)
endif ()
add_compile_definitions(BBL_RELEASE_TO_PUBLIC=1 USE_TBB TBB_USE_CAPTURED_EXCEPTION=0 CGAL_LINKED_WITH_TBB ORCA_CORE_SLICING_ONLY)

set(Boost_NO_SYSTEM_PATHS OFF)
set(CMAKE_POLICY_DEFAULT_CMP0167 NEW)
set(ORCA_BOOST_COMPONENTS system filesystem thread log log_setup locale regex chrono atomic date_time iostreams program_options nowide)
find_package(Boost 1.83 REQUIRED COMPONENTS ${ORCA_BOOST_COMPONENTS})
find_package(TBB REQUIRED)
find_package(Threads REQUIRED)
find_package(ZLIB REQUIRED)
find_package(PNG REQUIRED)
find_package(JPEG REQUIRED)
find_package(EXPAT REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(NLopt REQUIRED)
find_package(cereal REQUIRED)
if (ORCA_CGAL_DIR)
    set(CGAL_DIR "${ORCA_CGAL_DIR}")
endif ()
set(CGAL_DO_NOT_WARN_ABOUT_CMAKE_BUILD_TYPE ON CACHE BOOL "" FORCE)
find_package(CGAL 6.2 REQUIRED)
unset(CMAKE_POLICY_DEFAULT_CMP0167)

if (ORCA_EIGEN_DIR)
    add_library(Eigen3::Eigen INTERFACE IMPORTED)
    set_target_properties(Eigen3::Eigen PROPERTIES INTERFACE_INCLUDE_DIRECTORIES "${ORCA_EIGEN_DIR}")
else ()
    find_package(Eigen3 5 REQUIRED)
endif ()

find_path(LIBNOISE_INCLUDE_DIR libnoise/noise.h)
find_library(LIBNOISE_LIBRARY NAMES noise libnoise libnoise_static liblibnoise_static)
if (NOT LIBNOISE_INCLUDE_DIR OR NOT LIBNOISE_LIBRARY)
    message(FATAL_ERROR "libnoise not found (headers libnoise/noise.h and the library)")
endif ()
add_library(noise::noise UNKNOWN IMPORTED)
set_target_properties(noise::noise PROPERTIES IMPORTED_LOCATION "${LIBNOISE_LIBRARY}" INTERFACE_INCLUDE_DIRECTORIES "${LIBNOISE_INCLUDE_DIR}")

# what Orca's top-level file calls boost_libs and boost_headeronly
add_library(boost_headeronly INTERFACE)
target_include_directories(boost_headeronly SYSTEM INTERFACE ${Boost_INCLUDE_DIRS})
add_library(boost_libs INTERFACE)
target_link_libraries(boost_libs INTERFACE boost_headeronly)
# Boost's own CMake files (config mode) define Boost::<component> targets and do not fill Boost_LIBRARIES. Their files are linked by path:
# naming the targets themselves would also put Boost's compile definitions on every source file (and rebuild all of them).
foreach (_c ${ORCA_BOOST_COMPONENTS})
    if (TARGET Boost::${_c})
        target_link_libraries(boost_libs INTERFACE "$<TARGET_LINKER_FILE:Boost::${_c}>")
    endif ()
endforeach ()
if (Boost_LIBRARIES)
    target_link_libraries(boost_libs INTERFACE ${Boost_LIBRARIES})
endif ()

# ---- Orca's bundled libraries (deps_src), the ones the engine uses ------------------------------------------------------
set(_deps "${ORCA_SRC}/deps_src")
foreach (_d agg ankerl earcut fast_float nanosvg nlohmann stb_dxt admesh clipper2 glu-libtess libigl mcut miniz qhull qoi semver)
    add_subdirectory("${_deps}/${_d}" "${CMAKE_CURRENT_BINARY_DIR}/deps/${_d}")
endforeach ()

# admesh includes "libslic3r/..." headers; Orca's top-level file puts src/ on every target's include path, ours does it for the ones that need it
target_include_directories(admesh PRIVATE "${ORCA_SRC}/src")

# ---- the engine ----------------------------------------------------------------------------------------------------------
add_library(libslic3r STATIC ${ORCA_CORE_SOURCES} "${CMAKE_CURRENT_SOURCE_DIR}/src/nanosvg_impl.cpp" "${CMAKE_CURRENT_BINARY_DIR}/libslic3r_version.h")
target_compile_definitions(libslic3r PUBLIC USE_TBB TBB_USE_CAPTURED_EXCEPTION=0 CGAL_LINKED_WITH_TBB ORCA_CORE_SLICING_ONLY)
target_include_directories(libslic3r
    PRIVATE "${ORCA_SRC}/src/libslic3r"
    PUBLIC  "${ORCA_SRC}/src" "${CMAKE_CURRENT_BINARY_DIR}" "${_deps}" ${EXPAT_INCLUDE_DIRS})
if (WIN32)
    target_compile_definitions(libslic3r PUBLIC XML_STATIC "WIN32_LEAN_AND_MEAN=" NOMINMAX)
    target_link_libraries(libslic3r PRIVATE Psapi bcrypt)
endif ()
target_link_libraries(libslic3r
    PUBLIC  Eigen3::Eigen admesh libigl libnest2d miniz
    PRIVATE ${CMAKE_DL_LIBS} EXPAT::EXPAT ${JPEG_LIBRARIES} boost_libs cereal::cereal Clipper2 glu-libtess libslic3r_cgal mcut noise::noise
            PNG::PNG qhull qoi semver TBB::tbb TBB::tbbmalloc ZLIB::ZLIB OpenSSL::Crypto Threads::Threads)

# libnest2d (the arrange code) links the engine by name
add_subdirectory("${_deps}/libnest2d" "${CMAKE_CURRENT_BINARY_DIR}/deps/libnest2d")

# the part that needs CGAL: kept in its own library so CGAL's floating point flags stay inside it
add_library(libslic3r_cgal STATIC ${ORCA_CORE_CGAL_SOURCES})
target_include_directories(libslic3r_cgal PRIVATE "${ORCA_SRC}/src/libslic3r" "${ORCA_SRC}/src" "${CMAKE_CURRENT_BINARY_DIR}" "${_deps}")
get_target_property(_cgal_tgt CGAL::CGAL ALIASED_TARGET)
if (NOT TARGET ${_cgal_tgt})
    set(_cgal_tgt CGAL::CGAL)
endif ()
get_target_property(_opts ${_cgal_tgt} INTERFACE_COMPILE_OPTIONS)
if (_opts)
    set(_opts_bad "${_opts}")
    set(_opts_good "${_opts}")
    list(FILTER _opts_bad INCLUDE REGEX frounding-math)
    list(FILTER _opts_good EXCLUDE REGEX frounding-math)
    set_target_properties(${_cgal_tgt} PROPERTIES INTERFACE_COMPILE_OPTIONS "${_opts_good}")
    target_compile_options(libslic3r_cgal PRIVATE "${_opts_bad}")
endif ()
target_compile_definitions(libslic3r_cgal PRIVATE CGAL_LINKED_WITH_TBB)
target_link_libraries(libslic3r_cgal PRIVATE ${_cgal_tgt} admesh libigl mcut boost_libs TBB::tbb Eigen3::Eigen)

# the sources are Orca's, with Orca's warnings; we do not read them
if (NOT MSVC)
    target_compile_options(libslic3r PRIVATE -w)
    target_compile_options(libslic3r_cgal PRIVATE -w)
endif ()

if (ORCA_CORE_TESTS)
    add_executable(orca_core_slice_cube tests/slice_cube.cpp)
    target_link_libraries(orca_core_slice_cube PRIVATE libslic3r boost_libs TBB::tbb)
    add_executable(orca_core_slice_3mf tests/slice_3mf.cpp)
    target_link_libraries(orca_core_slice_3mf PRIVATE libslic3r boost_libs TBB::tbb)
endif ()

# ---- the Python module (SLC-2) -------------------------------------------------------------------------------------------
# cmake -DORCA_CORE_PYTHON=ON -Dpybind11_DIR=$(python -m pybind11 --cmakedir) ... ; the module is built as orca_core/_orca_core.<tag>
if (ORCA_CORE_PYTHON)
    find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
    find_package(pybind11 CONFIG REQUIRED)
    file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/ORCA_PIN" _pin_commit REGEX "^commit=")
    string(REPLACE "commit=" "" _pin_commit "${_pin_commit}")
    pybind11_add_module(_orca_core bindings/orca_core_module.cpp)
    target_compile_definitions(_orca_core PRIVATE ORCA_CORE_ORCA_COMMIT="${_pin_commit}")
    target_link_libraries(_orca_core PRIVATE libslic3r boost_libs TBB::tbb)
    if (NOT MSVC)
        target_compile_options(_orca_core PRIVATE -w)
    endif ()
endif ()
