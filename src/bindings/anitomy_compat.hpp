#pragma once

#include <algorithm>
#include <cstddef>
#include <ranges>
#include <tuple>
#include <utility>

namespace muxtools_styx::compat {

// Anitomy uses these adaptors only on sized random-access token ranges.
// Tuple elements must remain references: parser passes mark the original tokens.
template <std::size_t N, std::ranges::viewable_range Range>
  requires std::ranges::random_access_range<Range> && std::ranges::sized_range<Range>
constexpr auto adjacent(Range&& range) {
  static_assert(N > 0);
  auto view = std::views::all(std::forward<Range>(range));
  using index_t = std::ranges::range_difference_t<decltype(view)>;
  const auto size = std::ranges::distance(view);
  const auto count = std::max(index_t{0}, size - static_cast<index_t>(N) + 1);
  return std::views::iota(index_t{0}, count) |
         std::views::transform([view](index_t index) {
           return [&]<std::size_t... I>(std::index_sequence<I...>) {
             return std::tie(view[index + static_cast<index_t>(I)]...);
           }(std::make_index_sequence<N>{});
         });
}

template <std::ranges::viewable_range Range>
  requires std::ranges::random_access_range<Range> && std::ranges::sized_range<Range>
constexpr auto enumerate(Range&& range) {
  auto view = std::views::all(std::forward<Range>(range));
  using index_t = std::ranges::range_difference_t<decltype(view)>;
  return std::views::iota(index_t{0}, std::ranges::distance(view)) |
         std::views::transform([view](index_t index) {
           return std::tuple<index_t, std::ranges::range_reference_t<decltype(view)>>{index, view[index]};
         });
}

}  // namespace muxtools_styx::compat
