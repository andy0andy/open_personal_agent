import { createContext } from "react";

/**
 * 所在的回答是否还在输出（AssistantMessage 提供）：代码块在输出中不着色，
 * 结束后再着色（设计 2026-10-22 3.9），免得每来一段都重新着色。
 */
export const MessageRunningContext = createContext(false);
