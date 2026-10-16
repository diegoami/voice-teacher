// Origin-scoped pending intent, additionally bound to learner/session. No grants.
export type Upload = {
  request_id: string;
  expected_revision: number;
  recording: Blob;
  media_type: string;
};
export type ControlOperation = "pause" | "resume" | "finish";
export type Control = {
  request_id: string;
  expected_revision: number;
  operation: ControlOperation;
};
export type Journal = {
  key: string;
  upload: Upload | null;
  control: Control | null;
};
type LegacyJournal = Journal & { finish?: Omit<Control, "operation"> | null };
const database = "voice-teacher-pending-v1",
  version = 2;
function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(database, version);
    let failed = false;
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("pending")) {
        db.createObjectStore("pending", { keyPath: "key" });
        return;
      }
      const cursor = request.transaction!.objectStore("pending").openCursor();
      cursor.onsuccess = () => {
        const row = cursor.result;
        if (!row) return;
        const value = row.value as LegacyJournal;
        const migrated: LegacyJournal = {
          ...value,
          upload: value.upload ?? null,
          control:
            value.control ??
            (value.finish ? { ...value.finish, operation: "finish" } : null),
        };
        delete migrated.finish;
        row.update(migrated);
        row.continue();
      };
    };
    request.onsuccess = () => {
      if (failed) {
        request.result.close();
        return;
      }
      request.result.onversionchange = () => request.result.close();
      resolve(request.result);
    };
    request.onerror = () => {
      failed = true;
      reject(
        new Error(
          "Pending recording storage is unavailable. Reload the app and enable site storage.",
        ),
      );
    };
    request.onblocked = () => {
      failed = true;
      reject(
        new Error(
          "Close other app tabs and reload to update recording storage.",
        ),
      );
    };
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
    const store = tx.objectStore("pending"),
      request = store.get(key);
    let result: Journal;
    request.onsuccess = () => {
      try {
        result = request.result || { key, upload: null, control: null };
        if (update) {
          result = update(result);
          if (result.key !== key) throw new Error("journal identity changed");
          if (!result.upload && !result.control) store.delete(key);
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
          "Recording could not be saved. Free some site storage and try again.",
        ),
      );
    };
  });
}
