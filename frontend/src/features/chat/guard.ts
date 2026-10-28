/** 同一时间只跑一个的门：上一个还没结束时再调用直接忽略（连点按钮只发一次请求）。 */
export interface Guard {
  run: (task: () => Promise<void>) => Promise<void>;
}

export function createGuard(): Guard {
  let busy = false;
  return {
    async run(task) {
      if (busy) return;
      busy = true;
      try {
        await task();
      } finally {
        busy = false;
      }
    },
  };
}
