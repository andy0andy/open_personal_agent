import type { ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MemoryPart } from "./parts";

const render = (data: Record<string, unknown>) =>
  renderToStaticMarkup(
    <MemoryPart
      {...({ data, type: "data", name: "memory" } as ComponentProps<typeof MemoryPart>)}
    />,
  );

describe("聊天里的记忆提示", () => {
  it("可疑的记忆：说明与内容分开写，不连着两个冒号（审查 Minor 7）", () => {
    const html = render({
      id: "m1",
      content: "以后都用英文回答",
      suspicious: "要求忽略之前的指令",
    });
    expect(html).toContain(
      "已记住，但像是“要求忽略之前的指令”，标为可疑：在知识库页确认前不会用上。内容：以后都用英文回答",
    );
  });
});
