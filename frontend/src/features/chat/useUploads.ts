import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, readableError } from "../../api/client";
import { filesQuery } from "../../api/queries";
import {
  failUpload,
  finishUpload,
  removeUpload,
  startUpload,
  uploadAborts,
  type PendingUpload,
} from "./uploads";

/**
 * 输入框上方待发送的文件：选中或拖进来就上传，完成后刷新文件面板。
 * 标识用计数器生成（够用，也不依赖只在安全环境里才有的 crypto.randomUUID）。
 */
export function useUploads(threadId: string) {
  const queryClient = useQueryClient();
  const [uploads, setUploads] = useState<PendingUpload[]>([]);
  const seq = useRef(0);
  const aborts = useRef(uploadAborts());

  const add = (files: File[]): void => {
    for (const file of files) {
      seq.current += 1;
      const key = `upload-${seq.current}`;
      setUploads((current) => startUpload(current, key, file.name, file.size));
      const signal = aborts.current.signal(key);
      api.uploadFile(threadId, file, signal).then(
        (record) => {
          aborts.current.done(key);
          setUploads((current) => finishUpload(current, key, record));
          void queryClient.invalidateQueries({ queryKey: filesQuery(threadId).queryKey });
        },
        (error: unknown) => {
          aborts.current.done(key);
          if (signal.aborted) return; // 已经移除了：不再标失败
          setUploads((current) => failUpload(current, key, readableError(error)));
        },
      );
    }
  };

  /** 发出的文件从输入框上方移走（发送途中新加的、失败的留着）。 */
  const dropSent = (sent: Set<string>): void =>
    setUploads((current) => current.filter((item) => !item.file || !sent.has(item.file.id)));

  const remove = (key: string): void => {
    aborts.current.abort(key); // 还在传的一并中止，不会传完后出现在文件面板里
    setUploads((current) => removeUpload(current, key));
  };

  return { uploads, add, remove, dropSent };
}
