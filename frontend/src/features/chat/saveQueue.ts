/** 会话设置（模型、审批权限）的保存队列：按顺序保存；发送前等正在进行的保存结束。 */
export interface SaveQueue {
  /** 排在前一次之后执行；失败照常抛给调用方（由它提示并恢复原值）。 */
  run(task: () => Promise<void>): Promise<void>;
  /**
   * 等发起时还在进行的保存结束：最后一次失败时为 false（这条消息不发）。
   * 没有进行中的保存时立即为 true：以前的失败已经提示过、选择框也已恢复，不挡之后的发送。
   */
  idle(): Promise<boolean>;
}

export function createSaveQueue(): SaveQueue {
  let tail: Promise<boolean> = Promise.resolve(true);
  let pending = 0;
  return {
    run(task) {
      pending += 1;
      const result = tail.then(task);
      tail = result
        .then(
          () => true,
          () => false,
        )
        .finally(() => {
          pending -= 1;
        });
      return result;
    },
    idle() {
      return pending === 0 ? Promise.resolve(true) : tail;
    },
  };
}
