import clsx from "clsx";
import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  align?: "left" | "right";
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string | number;
  rowClassName?: (row: T) => string | undefined;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
}

/** Minimal typed table. Cell content is rendered by the caller (no math here). */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowClassName,
  onRowClick,
  empty = "데이터 없음",
}: DataTableProps<T>) {
  if (rows.length === 0) return <p className="py-4 text-center text-xs text-ink-faint">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-border text-ink-muted">
            {columns.map((c) => (
              <th
                key={c.key}
                className={clsx(
                  "px-2 py-1.5 font-medium",
                  c.align === "right" ? "text-right" : "text-left",
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={clsx(
                "border-b border-border/60 last:border-0",
                onRowClick && "cursor-pointer hover:bg-subtle",
                rowClassName?.(row),
              )}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={clsx(
                    "px-2 py-1.5",
                    c.align === "right" && "text-right tabular-nums",
                    c.className,
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
