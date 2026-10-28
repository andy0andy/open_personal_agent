import { describe, expect, it } from "vitest";
import { type EntryLike, readDroppedEntries } from "./dropped";

const file = (name: string): EntryLike => ({
  isFile: true,
  isDirectory: false,
  name,
  file: (resolve) => resolve(new File([name], name)),
});

/** 浏览器每次 readEntries 最多给一批（Chrome 100 个），要一直读到返回空为止。 */
const folder = (name: string, children: EntryLike[], batch = 1): EntryLike => ({
  isFile: false,
  isDirectory: true,
  name,
  createReader: () => {
    let at = 0;
    return {
      readEntries: (resolve) => {
        resolve(children.slice(at, at + batch));
        at += batch;
      },
    };
  },
});

describe("读出拖进来的文件夹", () => {
  it("一层层读出全部文件，路径带文件夹名（和选择文件夹时一样）", async () => {
    const dropped = [
      folder("excel", [file("SKILL.md"), folder("scripts", [file("a.py"), file("b.py")])]),
    ];
    const files = await readDroppedEntries(dropped);
    expect(files.map((item) => item.path)).toEqual([
      "excel/SKILL.md",
      "excel/scripts/a.py",
      "excel/scripts/b.py",
    ]);
    expect(files[0]?.file.name).toBe("SKILL.md");
  });

  it("直接拖入的单个文件路径就是文件名", async () => {
    expect((await readDroppedEntries([file("SKILL.md")])).map((item) => item.path)).toEqual([
      "SKILL.md",
    ]);
  });
});
