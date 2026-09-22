import {
  columnFilteringFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  globalFilteringFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_datetime,
  sortFn_text,
  tableFeatures,
} from "@tanstack/react-table";

/**
 * Shared TanStack Table v9 capabilities for terminal books.
 *
 * The core row model is always included. Visibility is registered because
 * every table renders `row.getVisibleCells()`. Sizing is registered because
 * a ranking column sets an explicit width. Sorting registers the comparators
 * the automatic sorter chooses from column values. Filtering is a separate
 * set for tables that search or filter rows in the table itself.
 */
export const sortedTableFeatures = tableFeatures({
  columnSizingFeature,
  columnVisibilityFeature,
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: {
    alphanumeric: sortFn_alphanumeric,
    basic: sortFn_basic,
    datetime: sortFn_datetime,
    text: sortFn_text,
  },
});

export const filteredSortedTableFeatures = tableFeatures({
  ...sortedTableFeatures,
  columnFilteringFeature,
  globalFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { includesString: filterFn_includesString },
});

export type SortedTableFeatures = typeof sortedTableFeatures;
export type FilteredSortedTableFeatures = typeof filteredSortedTableFeatures;
