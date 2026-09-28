#include <cstddef>
#include <new>
#include <string>
#include <string_view>

#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/string_view.h>
#include <nanobind/stl/vector.h>

#include <anitomy.hpp>
#include <anitomy/detail/format.hpp>

namespace nb = nanobind;
using namespace nb::literals;

namespace {

void bind_element_kind(nb::module_& module) {
  nb::enum_<anitomy::ElementKind> kind(module, "ElementKind");

  // Use conventional uppercase Python enum names for the upstream kinds.
  kind.value("AUDIO_TERM", anitomy::ElementKind::AudioTerm)
      .value("DEVICE", anitomy::ElementKind::Device)
      .value("EPISODE", anitomy::ElementKind::Episode)
      .value("EPISODE_TITLE", anitomy::ElementKind::EpisodeTitle)
      .value("FILE_CHECKSUM", anitomy::ElementKind::FileChecksum)
      .value("FILE_EXTENSION", anitomy::ElementKind::FileExtension)
      .value("LANGUAGE", anitomy::ElementKind::Language)
      .value("OTHER", anitomy::ElementKind::Other)
      .value("PART", anitomy::ElementKind::Part)
      .value("RELEASE_GROUP", anitomy::ElementKind::ReleaseGroup)
      .value("RELEASE_INFORMATION", anitomy::ElementKind::ReleaseInformation)
      .value("RELEASE_VERSION", anitomy::ElementKind::ReleaseVersion)
      .value("SEASON", anitomy::ElementKind::Season)
      .value("SOURCE", anitomy::ElementKind::Source)
      .value("SUBTITLES", anitomy::ElementKind::Subtitles)
      .value("TITLE", anitomy::ElementKind::Title)
      .value("TYPE", anitomy::ElementKind::Type)
      .value("VIDEO_RESOLUTION", anitomy::ElementKind::VideoResolution)
      .value("VIDEO_TERM", anitomy::ElementKind::VideoTerm)
      .value("VOLUME", anitomy::ElementKind::Volume)
      .value("YEAR", anitomy::ElementKind::Year);
}

void bind_element(nb::module_& module) {
  nb::class_<anitomy::Element>(module, "Element")
      .def(nb::init<anitomy::ElementKind, std::string, std::size_t>(), "kind"_a, "value"_a, "position"_a)
      .def_ro("kind", &anitomy::Element::kind)
      .def_ro("value", &anitomy::Element::value)
      .def_ro("position", &anitomy::Element::position)
      .def(
          "__repr__",
          [](const anitomy::Element& element) {
            return "Element(kind=" + std::string{anitomy::detail::to_string(element.kind)} + ", value=" +
                   element.value + ", position=" + std::to_string(element.position) + ")";
          })
      .def(
          "__eq__",
          [](const anitomy::Element& left, const anitomy::Element& right) {
            return left.kind == right.kind && left.value == right.value && left.position == right.position;
          });
}

void bind_options(nb::module_& module) {
  nb::class_<anitomy::Options>(module, "Options")
      .def(
          "__init__",
          [](anitomy::Options* self,
             const bool parse_episode,
             const bool parse_episode_title,
             const bool parse_file_checksum,
             const bool parse_file_extension,
             const bool parse_part,
             const bool parse_release_group,
             const bool parse_season,
             const bool parse_title,
             const bool parse_video_resolution,
             const bool parse_year) {
            new (self) anitomy::Options{
                .parse_episode = parse_episode,
                .parse_episode_title = parse_episode_title,
                .parse_file_checksum = parse_file_checksum,
                .parse_file_extension = parse_file_extension,
                .parse_part = parse_part,
                .parse_release_group = parse_release_group,
                .parse_season = parse_season,
                .parse_title = parse_title,
                .parse_video_resolution = parse_video_resolution,
                .parse_year = parse_year,
            };
          },
          "parse_episode"_a = true,
          "parse_episode_title"_a = true,
          "parse_file_checksum"_a = true,
          "parse_file_extension"_a = true,
          "parse_part"_a = true,
          "parse_release_group"_a = true,
          "parse_season"_a = true,
          "parse_title"_a = true,
          "parse_video_resolution"_a = true,
          "parse_year"_a = true)
      .def_rw("parse_episode", &anitomy::Options::parse_episode)
      .def_rw("parse_episode_title", &anitomy::Options::parse_episode_title)
      .def_rw("parse_file_checksum", &anitomy::Options::parse_file_checksum)
      .def_rw("parse_file_extension", &anitomy::Options::parse_file_extension)
      .def_rw("parse_part", &anitomy::Options::parse_part)
      .def_rw("parse_release_group", &anitomy::Options::parse_release_group)
      .def_rw("parse_season", &anitomy::Options::parse_season)
      .def_rw("parse_title", &anitomy::Options::parse_title)
      .def_rw("parse_video_resolution", &anitomy::Options::parse_video_resolution)
      .def_rw("parse_year", &anitomy::Options::parse_year);
}

}  // namespace

NB_MODULE(_anitomy, module) {
  module.doc() = "Thin nanobind binding for Anitomy v2.";

  bind_element_kind(module);
  bind_element(module);
  bind_options(module);

  module.def("parse", &anitomy::parse, "text"_a, "options"_a = anitomy::Options{});
}
