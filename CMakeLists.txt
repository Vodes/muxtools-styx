cmake_minimum_required(VERSION 3.26...4.0)

project(muxtools_styx LANGUAGES CXX)

find_package(
  Python 3.12
  REQUIRED
  COMPONENTS Interpreter Development.Module Development.SABIModule
)
find_package(nanobind CONFIG REQUIRED)
add_subdirectory(subprojects/anitomy/include)

# libstdc++ only provides ranges::starts_with from GCC 16 onward.
# Patch a build-local header so the vendored source remains untouched.
file(READ subprojects/anitomy/include/anitomy/detail/tokenizer.hpp ANITOMY_TOKENIZER)
string(REPLACE
  "std::ranges::starts_with(keyword, prefix, equal_to)"
  "std::ranges::equal(keyword | std::views::take(prefix.size()), prefix, equal_to)"
  ANITOMY_TOKENIZER "${ANITOMY_TOKENIZER}"
)
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/anitomy_compat/anitomy/detail/tokenizer.hpp" "${ANITOMY_TOKENIZER}")

nanobind_add_module(_anitomy STABLE_ABI NB_STATIC src/bindings/anitomy.cpp)
target_include_directories(_anitomy BEFORE PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/anitomy_compat")
target_compile_features(_anitomy PRIVATE cxx_std_23)
target_link_libraries(_anitomy PRIVATE anitomy)

install(TARGETS _anitomy LIBRARY DESTINATION muxtools_styx RUNTIME DESTINATION muxtools_styx)
