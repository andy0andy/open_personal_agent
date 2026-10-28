import { useCallback, useState } from "react";

/** 对话页右侧面板：文件（正在预览的文件，null 为文件列表）或出处（回答引用的知识条目）。 */
export interface SidePanel {
  open: boolean;
  mode: "files" | "citation";
  fileId: string | null;
  itemId: string | null;
}

const CLOSED: SidePanel = { open: false, mode: "files", fileId: null, itemId: null };

export function useSidePanel() {
  const [panel, setPanel] = useState<SidePanel>(CLOSED);
  const openFile = useCallback(
    (fileId: string | null) => setPanel({ open: true, mode: "files", fileId, itemId: null }),
    [],
  );
  const openCitation = useCallback(
    (itemId: string) => setPanel({ open: true, mode: "citation", fileId: null, itemId }),
    [],
  );
  const close = useCallback(() => setPanel(CLOSED), []);
  // 顶栏的"文件"：开着文件面板时关上，否则打开文件列表
  const toggleFiles = useCallback(
    () =>
      setPanel((current) =>
        current.open && current.mode === "files"
          ? CLOSED
          : { open: true, mode: "files", fileId: null, itemId: null },
      ),
    [],
  );
  return {
    panel,
    openFile,
    openCitation,
    close,
    toggleFiles,
    filesOpen: panel.open && panel.mode === "files",
  };
}
