# Generate compatibility headers without modifying the Anitomy submodule.
set(ANITOMY_COMPAT_DIR "${CMAKE_CURRENT_BINARY_DIR}/anitomy_compat")

function(styx_patch_anitomy header)
  file(READ "${CMAKE_CURRENT_SOURCE_DIR}/subprojects/anitomy/include/${header}" content)
  string(REPLACE
    "std::ranges::starts_with(keyword, prefix, equal_to)"
    "std::ranges::equal(keyword | std::views::take(prefix.size()), prefix, equal_to)"
    content "${content}"
  )
  string(REPLACE "tokens | std::views::adjacent<3>" "muxtools_styx::compat::adjacent<3>(tokens)" content "${content}")
  string(REPLACE "tokens | adjacent<3>" "muxtools_styx::compat::adjacent<3>(tokens)" content "${content}")
  string(REPLACE "tokens | reverse | adjacent<2>" "muxtools_styx::compat::adjacent<2>(tokens | reverse)" content "${content}")
  string(REPLACE "tokens | enumerate" "muxtools_styx::compat::enumerate(tokens)" content "${content}")
  string(REPLACE
    "std::format(\"{}{}{}\", number.value, delimiter.value, fraction.value)"
    "number.value + delimiter.value + fraction.value"
    content "${content}"
  )
  # Floating-point conversion is only used by the upstream CLI's JSON reader.
  # Defer overload resolution so the Python parser does not require that API.
  string(REPLACE "inline float to_float(" "template <typename Float = float>\ninline Float to_float(" content "${content}")
  string(REPLACE "float value{.0f}" "Float value{.0f}" content "${content}")
  string(REPLACE "#pragma once" "#pragma once\n\n#include <anitomy_compat.hpp>" content "${content}")
  file(WRITE "${ANITOMY_COMPAT_DIR}/${header}" "${content}")
endfunction()

foreach(header IN ITEMS
    anitomy/detail/tokenizer.hpp
    anitomy/detail/util.hpp
    anitomy/detail/parser/episode.hpp
    anitomy/detail/parser/file_extension.hpp
    anitomy/detail/parser/season.hpp
    anitomy/detail/parser/year.hpp
)
  styx_patch_anitomy("${header}")
endforeach()
