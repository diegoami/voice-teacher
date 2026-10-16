// Only an unfinished recording/finish intent lives here. IndexedDB is scoped to
// the server origin; the key additionally binds learner and session. No grants.
export type Upload = {
  request_id: string;
  expected_revision: number;
  recording: Blob;
  media_type: string;
};
export type Finish = { request_id: string; expected_revision: number };
export type Journal = {
  key: string;
  upload: Upload | null;
  finish: Finish | null;
};
const database = "voice-teacher-pending-v1";
function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(database, 1);
    request.onupgradeneeded = () =>
      request.result.createObjectStore("pending", { keyPath: "key" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(
        new Error(
          "Pending recording storage is unavailable. Enable site storage and try again.",
        ),
      );
    request.onblocked = () =>
      reject(new Error("Close other app tabs to update recording storage."));
  });
}
export function journalKey(learner: string, session: string) {
  return JSON.stringify([learner, session]);
}
export async function journal(
  key: string,
  update?: (value: Journal) => Journal,
): Promise<Journal> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("pending", update ? "readwrite" : "readonly");
    const store = tx.objectStore("pending");
    const request = store.get(key);
    let result: Journal;
    request.onsuccess = () => {
      try {
        result = request.result || { key, upload: null, finish: null };
        if (update) {
          result = update(result);
          if (!result.upload && !result.finish) store.delete(key);
          else store.put(result);
        }
      } catch {
        tx.abort();
      }
    };
    tx.oncomplete = () => {
      db.close();
      resolve(result);
    };
    tx.onabort = tx.onerror = () => {
      db.close();
      reject(
        new Error(
          "Recording could not be saved. Free some site storage and record again.",
        ),
      );
    };
  });
}
