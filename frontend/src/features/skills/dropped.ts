/**
 * 拖放接口里文件与文件夹条目的最小形状（浏览器的 FileSystemFileEntry / FileSystemDirectoryEntry），
 * 只写用到的部分，便于测试。
 */
export type EntryLike =
  | {
      isFile: true;
      isDirectory: false;
      name: string;
      file: (resolve: (file: File) => void, reject?: (error: unknown) => void) => void;
    }
  | {
      isFile: false;
      isDirectory: true;
      name: string;
      createReader: () => {
        readEntries: (
          resolve: (entries: EntryLike[]) => void,
          reject?: (error: unknown) => void,
        ) => void;
      };
    };

/** path 带文件夹层级，和"选择文件夹"时浏览器给的相对路径一样 */
export type DroppedFile = { path: string; file: File };

/**
 * 拖入文件夹时 dataTransfer.files 只有一个以文件夹命名的空条目，要按条目一层层读出里面的文件。
 * readEntries 每次只给一批（Chrome 最多 100 个），读到空为止。
 */
export async function readDroppedEntries(entries: EntryLike[]): Promise<DroppedFile[]> {
  const files: DroppedFile[] = [];
  const walk = async (entry: EntryLike, parent: string): Promise<void> => {
    const path = parent ? `${parent}/${entry.name}` : entry.name;
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => entry.file(resolve, reject));
      files.push({ path, file });
      return;
    }
    const reader = entry.createReader();
    for (;;) {
      const batch = await new Promise<EntryLike[]>((resolve, reject) =>
        reader.readEntries(resolve, reject),
      );
      if (batch.length === 0) return;
      for (const child of batch) await walk(child, path);
    }
  };
  for (const entry of entries) await walk(entry, "");
  return files;
}
