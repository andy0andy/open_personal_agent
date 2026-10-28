import type { ReactNode } from "react";
import { Panel } from "../../components/ui/Panel";

/** 工具、技能各用了几次（设计 2026-10-23 6.8）：名称与次数；这段时间没有时也显示这张表。 */
export function CountTable({
  title,
  rows,
}: {
  title: string;
  rows: { key: string; label: ReactNode; count: number }[];
}) {
  return (
    <Panel title={title}>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">这段时间没有</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm [&_td]:py-2 [&_td]:pr-4 [&_th]:pr-4 [&_th]:pb-2 [&_th]:font-normal">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th>名称</th>
                <th className="text-right">次数</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ key, label, count }) => (
                <tr key={key} className="border-t border-border">
                  <td>{label}</td>
                  <td className="text-right font-mono tabular-nums">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
