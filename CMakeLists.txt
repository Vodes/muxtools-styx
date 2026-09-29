cmake_minimum_required(VERSION 3.26...4.0)

project(muxtools_styx LANGUAGES CXX)

find_package(
  Python 3.12
  REQUIRED
  COMPONENTS Interpreter Development.Module Development.SABIModule
)
find_package(nanobind CONFIG REQUIRED)
add_subdirectory(subprojects/anitomy/include)

include(build_helpers/anitomy.cmake)

nanobind_add_module(_anitomy STABLE_ABI NB_STATIC src/bindings/anitomy.cpp)
target_include_directories(_anitomy BEFORE PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/anitomy_compat" "${CMAKE_CURRENT_SOURCE_DIR}/src/bindings")
target_compile_features(_anitomy PRIVATE cxx_std_23)
target_link_libraries(_anitomy PRIVATE anitomy)

install(TARGETS _anitomy LIBRARY DESTINATION muxtools_styx RUNTIME DESTINATION muxtools_styx)
