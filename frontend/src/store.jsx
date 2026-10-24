import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import { buildInitialData } from "./data";
import { IS_LIVE } from "./api";
import { extendRoleData } from "./role-data";
import { normalizeStoredSystemCopy } from "./system-copy";
const StoreContext = createContext(null);
const KEY = "dangjian.demo.v1";
function emptyData() {
  return {
    members: [],
    meetings: [],
    activities: [],
    tasks: [],
    knowledge: [],
    enrollments: [],
    learning: {},
    messages: [],
    notificationRead: false,
    personalMaterials: [],
    materialReceipts: [],
    developmentProfiles: {},
    accounts: [],
    tenants: [],
    auditEntries: [],
    platform: null,
  };
}
function readData() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY));
    return saved &&
      Array.isArray(saved.members) &&
      Array.isArray(saved.meetings)
      ? normalizeStoredSystemCopy(extendRoleData({ ...buildInitialData(), ...saved }))
      : extendRoleData(buildInitialData());
  } catch {
    return extendRoleData(buildInitialData());
  }
}
export function StoreProvider({ children }) {
  const [data, setData] = useState(() => (IS_LIVE ? emptyData() : readData()));
  const [toast, setToast] = useState(null);
  const [storageFailed, setStorageFailed] = useState(false);
  useEffect(() => {
    if (IS_LIVE) return;
    try {
      localStorage.setItem(KEY, JSON.stringify(data));
    } catch {
      setStorageFailed(true);
    }
  }, [data]);
  useEffect(() => {
    if (!toast) return;
    const timeout = setTimeout(() => setToast(null), 4200);
    return () => clearTimeout(timeout);
  }, [toast]);
  const notify = useCallback(
    (message, kind = "success") => setToast({ message, kind, id: Date.now() }),
    [],
  );
  const update = useCallback(
    (key, value) =>
      setData((prev) => ({
        ...prev,
        [key]: typeof value === "function" ? value(prev[key]) : value,
      })),
    [],
  );
  const resetPrivateData = useCallback(() => {
    setToast(null);
    if (IS_LIVE) setData(emptyData());
  }, []);
  return (
    <StoreContext.Provider
      value={{ data, update, notify, storageFailed, resetPrivateData }}
    >
      {children}
      {toast && (
        <div role="status" className={`toast ${toast.kind}`}>
          {toast.message}
        </div>
      )}
    </StoreContext.Provider>
  );
}
export function useStore() {
  return useContext(StoreContext);
}
