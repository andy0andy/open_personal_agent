import { createContext } from "react";

/** 在右侧面板里显示一条出处（由页面提供；回答里的出处按钮点击时调用）。 */
export const OpenCitationContext = createContext<(itemId: string) => void>(() => {});
