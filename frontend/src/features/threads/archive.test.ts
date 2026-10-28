import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { archivedThreadsQuery, threadsQuery } from "../../api/queries";
import type { Thread } from "../../api/types";
import { markViewed } from "./archive";

vi.mock("../../api/client", () => ({ api: { markViewed: vi.fn(async () => undefined) } }));

const thread = (id: string, activity: Thread["activity"] = null) =>
  ({ id, title: id, activity }) as unknown as Thread;

describe("看过了这个会话（积压小问题 B11）", () => {
  it("主列表与归档列表里它的“有新回答”都清掉", async () => {
    const client = new QueryClient();
    client.setQueryData<Thread[]>(threadsQuery.queryKey, [thread("a", "new")]);
    client.setQueryData<Thread[]>(archivedThreadsQuery.queryKey, [thread("b", "new")]);
    await markViewed(client, "a");
    await markViewed(client, "b");
    expect(client.getQueryData<Thread[]>(threadsQuery.queryKey)?.[0]?.activity).toBeNull();
    expect(client.getQueryData<Thread[]>(archivedThreadsQuery.queryKey)?.[0]?.activity).toBeNull();
  });
});
