import { createContext } from "react";

/** 在右侧文件面板里打开一个文件（由页面提供；产物卡片、附件标签点击时调用）。 */
export const OpenFileContext = createContext<(fileId: string) => void>(() => {});
