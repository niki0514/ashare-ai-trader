import type { ReactNode } from "react";

type DataTableProps = {
  headers: string[];
  rows: ReactNode[];
};

export function DataTable({ headers, rows }: DataTableProps) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  );
}
