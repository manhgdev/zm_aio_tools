import { useEffect, useMemo, useRef, useState } from "react";
import { localize, useLocale } from "@/app/i18n";
import {
  IconBatch,
  IconBook,
  IconClock,
  IconDownload,
  IconGear,
  IconPlay,
  IconVideo,
} from "@/shared/components/Icons";
import { BackTitle } from "@/shared/components/BackTitle";
import { OutputFolderField } from "@/shared/components/OutputFolderField";
import "./FlowPage.css";

type FlowTab = "create" | "queue" | "history" | "logs";
type RailItem =
  | "createImage"
  | "createVideo"
  | "queue"
  | "history"
  | "accounts"
  | "logs"
  | "help";
type JobStatus = "processing" | "queued" | "done" | "failed" | "cancelled";
type CreateKind = "video" | "image";
type ImageMode = "text" | "edit" | "reference";
type PromptInputType = "prompt" | "txt" | "csv" | "json";
type FlowJob = {
  id: string;
  index: number;
  kind: CreateKind;
  prompt: string;
  inputType: PromptInputType;
  createdAt: number;
  status: JobStatus;
  progress: number;
  account: string;
  output?: string;
  outputs?: string[];
  accountId?: string;
  error?: string | null;
  settings: {
    model: string;
    ratio: string;
    duration: string;
    resolution: string;
    outputDir: string;
  };
};
type FlowAccount = {
  id: string;
  label: string;
  plan: "Ultra" | "Pro";
  email: string;
  status: "online" | "reconnect" | "connecting";
  credits: number | null;
  used: number;
  creditsSyncedAt?: number | null;
  isDefault?: boolean;
  projectId?: string;
  error?: string;
};
type FlowLog = {
  id: string;
  level: "info" | "success" | "warning" | "error";
  event: string;
  jobId: string;
  accountId: string;
  message: string;
  details: Record<string, unknown>;
  createdAt: number;
};

type FlowSettings = {
  model: string;
  ratio: string;
  duration: string;
  count: number;
  account: string;
  outputDir: string;
  quality: string;
  resolution: string;
  seed: string;
  format: string;
  filePrefix: string;
  enhancePrompt: boolean;
  referenceStrength: number;
  autoDownload: boolean;
};
const FLOW_VIDEO_MODELS = [
  "Veo 3.1 - Lite",
  "Veo 3.1 - Lite [Lower Priority]",
  "Veo 3.1 - Fast",
  "Veo 3.1 - Quality",
  "Omni Flash",
] as const;
const FLOW_IMAGE_MODELS = [
  "Nano Banana Pro",
  "Nano Banana 2",
  "Nano Banana 2 Lite",
] as const;
const isVideoModel = (model: string) => FLOW_VIDEO_MODELS.includes(model as (typeof FLOW_VIDEO_MODELS)[number]);
const isImageModel = (model: string) =>
  FLOW_IMAGE_MODELS.includes(model as (typeof FLOW_IMAGE_MODELS)[number]);
const DRAFT_KEY = "zm-flow-veo:draft:v1";
const SETTINGS_KEY = "zm-flow-veo:settings:v1";
const WEB_AUTO_DOWNLOAD_DEFAULT_KEY = "zm-flow-veo:web-auto-download:v1";
const TAB_KEY = "zm-flow-veo:tab:v1";
const RAIL_KEY = "zm-flow-veo:rail:v1";
const ACCOUNTS_KEY = "zm-flow-veo:accounts:v1";
const CREATE_KIND_KEY = "zm-flow-veo:create-kind:v1";
const IMAGE_MODE_KEY = "zm-flow-veo:image-mode:v1";

function readText(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}
function defaultFlowOutputFolder(now = new Date()) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `flow_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}
function readSettings(): FlowSettings {
  const fallback: FlowSettings = {
    model: "Veo 3.1 - Fast",
    ratio: "16:9",
    duration: "8",
    count: 1,
    account: "Ultra 01",
    outputDir: defaultFlowOutputFolder(),
    quality: "Standard",
    resolution: "1K",
    seed: "",
    format: "PNG",
    filePrefix: "flow",
    enhancePrompt: true,
    referenceStrength: 70,
    autoDownload: true,
  };
  try {
    const saved = JSON.parse(
      localStorage.getItem(SETTINGS_KEY) || "{}",
    ) as Partial<FlowSettings>;
    const merged = {
      ...fallback,
      ...saved,
    };
    // Migrate the two provisional model labels used by the first Flow mock.
    if (merged.model === "Veo 3.1 Fast") merged.model = "Veo 3.1 - Fast";
    if (merged.model === "Veo 3.1 Quality") merged.model = "Veo 3.1 - Quality";
    if (/^Imagen 3/i.test(merged.model)) merged.model = "Nano Banana 2";
    if (!String(merged.outputDir || "").trim() || merged.outputDir === "flow_20250824_143022") {
      merged.outputDir = defaultFlowOutputFolder();
    }
    return merged;
  } catch {
    return fallback;
  }
}
function readAccounts(): FlowAccount[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(ACCOUNTS_KEY) || "");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
function IconImage({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m4 17 5-5 4 4 2-2 5 5" />
    </svg>
  );
}
function IconLog({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M5 4h14v16H5z" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </svg>
  );
}
async function flowRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

type DirectoryPickerWindow = Window & {
  showDirectoryPicker?: (options?: {
    id?: string;
    mode?: "read" | "readwrite";
    startIn?: string;
  }) => Promise<FileSystemDirectoryHandle>;
};

function safeWebFolderParts(value: string): string[] {
  return value
    .split(/[\\/]+/)
    .map((part) => part.replace(/[<>:"|?*\u0000-\u001f]/g, "-").trim())
    .filter((part) => part && part !== "." && part !== "..");
}

async function writeFlowOutputToDirectory(
  root: FileSystemDirectoryHandle,
  outputFolder: string,
  job: FlowJob,
  outputIndex: number,
) {
  let target = await root.getDirectoryHandle("flow", { create: true });
  for (const part of safeWebFolderParts(outputFolder || "flow")) {
    target = await target.getDirectoryHandle(part, { create: true });
  }
  const storedPath = job.outputs?.[outputIndex] || "";
  const filename = storedPath.split(/[\\/]/).pop() || `${job.kind}-${outputIndex + 1}`;
  const response = await fetch(`/api/flow/jobs/${job.id}/outputs/${outputIndex}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const file = await target.getFileHandle(filename, { create: true });
  const writable = await file.createWritable();
  await writable.write(await response.blob());
  await writable.close();
}

function downloadFlowOutput(job: FlowJob, outputIndex: number) {
  const link = document.createElement("a");
  link.href = `/api/flow/jobs/${job.id}/outputs/${outputIndex}?download=1`;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function normalizeFlowJobs(
  rows: Array<Record<string, unknown>>,
  accounts: FlowAccount[],
): FlowJob[] {
  return rows.map((raw) => {
    const rawSettings =
      raw.settings && typeof raw.settings === "object"
        ? (raw.settings as Record<string, unknown>)
        : {};
    return {
    id: String(raw.id),
    index: Number(raw.inputIndex || 0),
    kind: raw.kind === "image" ? "image" : "video",
    prompt: String(raw.prompt || ""),
    inputType:
      raw.inputType === "txt" || raw.inputType === "csv" || raw.inputType === "json"
        ? raw.inputType
        : "prompt",
    createdAt: Number(raw.createdAt || Date.now() / 1000),
    status:
      raw.status === "processing" ||
      raw.status === "queued" ||
      raw.status === "done" ||
      raw.status === "cancelled"
        ? raw.status
        : "failed",
    progress: Number(raw.progress || 0),
    accountId: String(raw.accountId || ""),
    account:
      accounts.find((item) => item.id === raw.accountId)?.label ||
      String(raw.accountId || ""),
    outputs: Array.isArray(raw.outputs) ? raw.outputs.map(String) : [],
    output: Array.isArray(raw.outputs) ? String(raw.outputs[0] || "") : "",
    error: raw.error ? String(raw.error) : null,
    settings: {
      model: String(rawSettings.model || (raw.kind === "image" ? "Nano Banana 2" : "Veo 3.1 - Fast")),
      ratio: String(rawSettings.ratio || "16:9"),
      duration: String(rawSettings.duration || "8"),
      resolution: String(rawSettings.resolution || "1K"),
      outputDir: String(rawSettings.outputDir || "flow"),
    },
  };
  });
}

function normalizeFlowAccounts(rows: FlowAccount[]): FlowAccount[] {
  return rows.map((account) => ({
    ...account,
    used: Number(account.used || 0),
    credits:
      account.creditsSyncedAt ||
      (account.status === "online" && account.projectId && account.credits != null)
        ? Number(account.credits)
        : null,
  }));
}

type FlowSnapshot = {
  accountData: { accounts: FlowAccount[] };
  jobData: { jobs: Array<Record<string, unknown>> };
};
let recentFlowSnapshot: { at: number; promise: Promise<FlowSnapshot> } | null = null;

function loadFlowSnapshot(): Promise<FlowSnapshot> {
  const now = Date.now();
  if (recentFlowSnapshot && now - recentFlowSnapshot.at < 5000) {
    return recentFlowSnapshot.promise;
  }
  const promise = Promise.all([
    flowRequest<{ accounts: FlowAccount[] }>("/api/flow/accounts"),
    flowRequest<{ jobs: Array<Record<string, unknown>> }>("/api/flow/jobs"),
  ]).then(([accountData, jobData]) => ({ accountData, jobData }));
  recentFlowSnapshot = { at: now, promise };
  promise.catch(() => {
    if (recentFlowSnapshot?.promise === promise) recentFlowSnapshot = null;
  });
  return promise;
}

export default function FlowPage({ onBack }: { onBack: () => void }) {
  const { locale } = useLocale();
  const t = (vi: string, en: string) => localize(locale, vi, en);
  const fileRef = useRef<HTMLInputElement>(null);
  const sourceRef = useRef<HTMLInputElement>(null);
  const webOutputDirectoryRef = useRef<FileSystemDirectoryHandle | null>(null);
  const [webOutputDirectoryName, setWebOutputDirectoryName] = useState("");
  const [tab, setTab] = useState<FlowTab>(() => {
    const saved = readText(TAB_KEY, "create");
    return saved === "queue" || saved === "history" || saved === "logs"
      ? saved
      : "create";
  });
  const [railOpen, setRailOpen] = useState(
    () => readText(RAIL_KEY, "1") === "1",
  );
  const [prompt, setPrompt] = useState(() =>
    readText(
      DRAFT_KEY,
      "Tokyo về đêm, phố Shibuya ướt sau cơn mưa, ánh đèn neon phản chiếu trên mặt đường.\n\nBuổi sáng yên bình bên hồ trong rừng thông, sương mù nhẹ trên mặt nước.\n\nThành phố tương lai lúc hoàng hôn, xe bay lướt qua các tòa nhà chọc trời.",
    ),
  );
  const [settings, setSettings] = useState<FlowSettings>(readSettings);
  const [importName, setImportName] = useState("");
  const [promptInputType, setPromptInputType] = useState<PromptInputType>("prompt");
  const [jobs, setJobs] = useState<FlowJob[]>([]);
  const [logs, setLogs] = useState<FlowLog[]>([]);
  const [createKind, setCreateKind] = useState<CreateKind>(() =>
    readText(CREATE_KIND_KEY, "video") === "image" ? "image" : "video",
  );
  const [imageMode, setImageMode] = useState<ImageMode>(() => {
    const saved = readText(IMAGE_MODE_KEY, "text");
    return saved === "edit" || saved === "reference" ? saved : "text";
  });
  const [sourceFiles, setSourceFiles] = useState<File[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [utilityView, setUtilityView] = useState<"accounts" | "help" | null>(
    null,
  );
  const [accounts, setAccounts] = useState<FlowAccount[]>(readAccounts);
  const [editingAccount, setEditingAccount] = useState<string | "new" | null>(
    null,
  );
  const [accountDraft, setAccountDraft] = useState({
    label: "",
    email: "",
    plan: "Pro" as FlowAccount["plan"],
  });
  const [apiError, setApiError] = useState("");
  const [logsCopied, setLogsCopied] = useState(false);
  const [backendReady, setBackendReady] = useState(false);
  const [isDesktopApp, setIsDesktopApp] = useState(false);
  const [runtimeKnown, setRuntimeKnown] = useState(false);
  const completedOutputsRef = useRef<Set<string> | null>(null);
  const [preview, setPreview] = useState<{
    job: FlowJob;
    outputIndex: number;
  } | null>(null);
  const [confirmAction, setConfirmAction] = useState<{
    message: string;
    confirmLabel: string;
    run: () => void;
  } | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY, prompt);
    } catch {}
  }, [prompt]);
  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {}
  }, [settings]);
  useEffect(() => {
    try {
      localStorage.setItem(TAB_KEY, tab);
    } catch {}
  }, [tab]);
  useEffect(() => {
    try {
      localStorage.setItem(RAIL_KEY, railOpen ? "1" : "0");
    } catch {}
  }, [railOpen]);
  useEffect(() => {
    try {
      localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(accounts));
    } catch {}
  }, [accounts]);
  useEffect(() => {
    try {
      localStorage.setItem(CREATE_KIND_KEY, createKind);
    } catch {}
  }, [createKind]);
  useEffect(() => {
    try {
      localStorage.setItem(IMAGE_MODE_KEY, imageMode);
    } catch {}
  }, [imageMode]);
  useEffect(() => {
    let active = true;
    const loadInitialSnapshot = async () => {
      try {
        const { accountData, jobData } = await loadFlowSnapshot();
        if (!active) return;
        const loadedAccounts = normalizeFlowAccounts(accountData.accounts);
        setAccounts(loadedAccounts);
        setJobs(normalizeFlowJobs(jobData.jobs, loadedAccounts));
        setBackendReady(true);
        setApiError("");
      } catch (error) {
        if (active) {
          setBackendReady(false);
          setApiError(error instanceof Error ? error.message : String(error));
        }
      }
    };
    void loadInitialSnapshot();
    return () => {
      active = false;
    };
  }, []);
  const hasActiveFlowJobs = jobs.some(
    (job) => job.status === "processing" || job.status === "queued",
  );
  const hasConnectingAccounts = accounts.some((account) => account.status === "connecting");
  useEffect(() => {
    if (!backendReady || !hasActiveFlowJobs) return;
    let active = true;
    const refreshJobs = () =>
      void flowRequest<{ jobs: Array<Record<string, unknown>>; accounts?: FlowAccount[] }>("/api/flow/jobs")
        .then((data) => {
          if (!active) return;
          const refreshedAccounts = data.accounts
            ? normalizeFlowAccounts(data.accounts)
            : accounts;
          if (data.accounts) setAccounts(refreshedAccounts);
          setJobs(normalizeFlowJobs(data.jobs, refreshedAccounts));
        })
        .catch((error) => {
          if (active) setApiError(error instanceof Error ? error.message : String(error));
        });
    const timer = window.setInterval(refreshJobs, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [accounts, backendReady, hasActiveFlowJobs]);
  useEffect(() => {
    if (tab !== "logs") return;
    let active = true;
    const refreshLogs = () =>
      void flowRequest<{ logs: FlowLog[] }>("/api/flow/logs")
        .then((data) => { if (active) setLogs(data.logs); })
        .catch(() => undefined);
    refreshLogs();
    if (!hasActiveFlowJobs) return () => { active = false; };
    const timer = window.setInterval(refreshLogs, 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [hasActiveFlowJobs, tab]);
  useEffect(() => {
    if (!hasConnectingAccounts) return;
    let active = true;
    const refreshAccounts = () =>
      void flowRequest<{ accounts: FlowAccount[] }>("/api/flow/accounts")
        .then((data) => { if (active) setAccounts(data.accounts); })
        .catch(() => undefined);
    const timer = window.setInterval(refreshAccounts, 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [hasConnectingAccounts]);
  useEffect(() => {
    void flowRequest<{ desktop?: boolean }>("/api/config")
      .then((data) => setIsDesktopApp(Boolean(data.desktop)))
      .catch(() => setIsDesktopApp(false))
      .finally(() => setRuntimeKnown(true));
  }, []);
  useEffect(() => {
    if (!runtimeKnown || isDesktopApp) return;
    try {
      if (localStorage.getItem(WEB_AUTO_DOWNLOAD_DEFAULT_KEY)) return;
      localStorage.setItem(WEB_AUTO_DOWNLOAD_DEFAULT_KEY, "1");
      setSettings((current) => ({ ...current, autoDownload: true }));
    } catch {
      setSettings((current) => ({ ...current, autoDownload: true }));
    }
  }, [isDesktopApp, runtimeKnown]);
  useEffect(() => {
    if (!backendReady || !runtimeKnown) return;
    const completed = jobs.flatMap((job) =>
      job.status === "done"
        ? (job.outputs || []).map((_output, outputIndex) => ({
            key: `${job.id}:${outputIndex}`,
            job,
            outputIndex,
          }))
        : [],
    );
    if (!completedOutputsRef.current) {
      completedOutputsRef.current = new Set(completed.map((item) => item.key));
      return;
    }
    for (const item of completed) {
      if (completedOutputsRef.current.has(item.key)) continue;
      completedOutputsRef.current.add(item.key);
      if (!isDesktopApp && settings.autoDownload) {
        if (webOutputDirectoryRef.current) {
          void writeFlowOutputToDirectory(
            webOutputDirectoryRef.current,
            item.job.settings.outputDir || settings.outputDir,
            item.job,
            item.outputIndex,
          ).catch((error) =>
            setApiError(error instanceof Error ? error.message : String(error)),
          );
        } else {
          downloadFlowOutput(item.job, item.outputIndex);
        }
      }
    }
  }, [backendReady, runtimeKnown, isDesktopApp, jobs, settings.autoDownload]);
  useEffect(() => {
    if (!preview) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreview(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [preview]);

  const promptCount = useMemo(
    () =>
      prompt
        .split(/\n\s*\n/)
        .map((item) => item.trim())
        .filter(Boolean).length,
    [prompt],
  );
  const latestCompletedVideo = jobs.find(
    (job) => job.kind === "video" && job.status === "done" && job.outputs?.length,
  );
  const displayedAccount =
    accounts.find((account) => account.label === settings.account) ||
    accounts.find((account) => account.isDefault) ||
    accounts[0];
  const statusText = (status: JobStatus) =>
    status === "processing"
      ? t("Đang xử lý", "Processing")
      : status === "queued"
        ? t("Đang chờ", "Queued")
        : status === "done"
          ? t("Hoàn thành", "Completed")
          : status === "cancelled"
            ? t("Đã hủy", "Cancelled")
            : t("Lỗi", "Failed");
  const jobErrorText = (error: string) =>
    error.startsWith("FLOW_EMPTY_OUTPUT")
      ? t(
          "Flow không trả về file video/ảnh. Job chưa thành công.",
          "Flow returned no video/image file. The job did not succeed.",
        )
      : error;
  const showCreate = tab === "create";
  const activateRail = (item: RailItem) => {
    if (item === "createImage" || item === "createVideo") {
      setUtilityView(null);
      setCreateKind(item === "createImage" ? "image" : "video");
      setSettings((current) => ({
        ...current,
        model:
          item === "createImage"
            ? isImageModel(current.model)
              ? current.model
              : "Nano Banana 2"
            : isVideoModel(current.model)
              ? current.model
              : "Veo 3.1 - Fast",
      }));
      setTab("create");
    } else if (item === "queue" || item === "history" || item === "logs") {
      setUtilityView(null);
      setTab(item);
    } else setUtilityView(item);
  };
  const importPrompts = (file?: File) => {
    if (!file) return;
    setImportName(file.name);
    const extension = file.name.split(".").pop()?.toLowerCase();
    setPromptInputType(
      extension === "csv" || extension === "json" ? extension : "txt",
    );
    const reader = new FileReader();
    reader.onload = () =>
      setPrompt((current) =>
        current.trim()
          ? `${current.trim()}\n\n${String(reader.result || "").trim()}`
          : String(reader.result || ""),
      );
    reader.readAsText(file);
  };
  const pastePrompt = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text.trim()) {
        setApiError(t("Clipboard đang trống.", "Clipboard is empty."));
        return;
      }
      setPrompt(text);
      setPromptInputType("prompt");
      setImportName("");
      setApiError("");
    } catch {
      setApiError(
        t(
          "Không đọc được clipboard. Hãy cấp quyền dán hoặc dùng Cmd/Ctrl+V.",
          "Could not read the clipboard. Allow paste access or use Cmd/Ctrl+V.",
        ),
      );
    }
  };
  const createFlowJobs = async () => {
    const prompts = prompt
      .split(/\n\s*\n/)
      .map((item) => item.trim())
      .filter(Boolean);
    const account =
      accounts.find((item) => item.label === settings.account) ||
      accounts.find((item) => item.isDefault);
    if (!prompts.length || !account) {
      setApiError(
        t(
          "Cần prompt và tài khoản Flow đã kết nối.",
          "A prompt and connected Flow account are required.",
        ),
      );
      return;
    }
    try {
      const effectiveSettings = settings.outputDir.trim()
        ? settings
        : { ...settings, outputDir: defaultFlowOutputFolder() };
      if (effectiveSettings !== settings) {
        setSettings(effectiveSettings);
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(effectiveSettings));
      }
      let uploaded: string[] = [];
      if (sourceFiles.length) {
        const form = new FormData();
        sourceFiles.forEach((file) => form.append("files", file));
        const data = await flowRequest<{ files: Array<{ path: string }> }>(
          "/api/flow/assets",
          { method: "POST", body: form },
        );
        uploaded = data.files.map((item) => item.path);
      }
      const created = await flowRequest<{ jobs: Array<Record<string, unknown>> }>("/api/flow/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompts,
          kind: createKind,
          mode:
            createKind === "image"
              ? imageMode
              : sourceFiles.length
                ? "frame"
                : "text",
          accountId: account.id,
          inputType: promptInputType,
          sourceFiles: uploaded,
          settings: effectiveSettings,
        }),
      });
      setJobs((current) => [
        ...normalizeFlowJobs(created.jobs, accounts),
        ...current.filter((item) => !created.jobs.some((row) => String(row.id) === item.id)),
      ]);
      setApiError("");
      setTab("queue");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error));
    }
  };
  const addAccount = () => {
    setAccountDraft({ label: "", email: "", plan: "Pro" });
    setEditingAccount("new");
  };
  const editAccount = (account: FlowAccount) => {
    setAccountDraft({
      label: account.label,
      email: account.email,
      plan: account.plan,
    });
    setEditingAccount(account.id);
  };
  const saveAccount = async () => {
    if (!accountDraft.label.trim() || !accountDraft.email.trim()) return;
    try {
      const editing = accounts.find((item) => item.id === editingAccount);
      const url =
        editingAccount === "new"
          ? "/api/flow/accounts"
          : `/api/flow/accounts/${editingAccount}`;
      const savedAccount = await flowRequest<FlowAccount>(url, {
        method: editingAccount === "new" ? "POST" : "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...accountDraft,
          projectId: editing?.projectId || "",
          isDefault: editing?.isDefault || false,
        }),
      });
      setAccounts((current) => [savedAccount, ...current.filter((item) => item.id !== savedAccount.id)]);
      setEditingAccount(null);
      setApiError("");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error));
    }
  };
  const deleteAccount = (account: FlowAccount) => {
    setConfirmAction({
      message: t(`Xóa tài khoản ${account.label}?`, `Delete account ${account.label}?`),
      confirmLabel: t("Xóa tài khoản", "Delete account"),
      run: () => void flowRequest(`/api/flow/accounts/${account.id}`, { method: "DELETE" })
        .then(() => setAccounts((current) => current.filter((item) => item.id !== account.id)))
        .catch((error) => setApiError(error instanceof Error ? error.message : String(error))),
    });
  };
  const updateJob = (raw: Record<string, unknown>) => {
    const next = normalizeFlowJobs([raw], accounts)[0];
    setJobs((current) => current.map((item) => item.id === next.id ? next : item));
  };
  const cancelJob = (id: string) =>
    void flowRequest<Record<string, unknown>>(`/api/flow/jobs/${id}/cancel`, { method: "POST" })
      .then(updateJob)
      .catch((error) => setApiError(error instanceof Error ? error.message : String(error)));
  const retryJob = (id: string) =>
    void flowRequest<Record<string, unknown>>(`/api/flow/jobs/${id}/retry`, { method: "POST" })
      .then(updateJob)
      .catch((error) => setApiError(error instanceof Error ? error.message : String(error)));
  const deleteJob = (id: string) => {
    setConfirmAction({
      message: t("Xóa job này khỏi danh sách?", "Delete this job from the list?"),
      confirmLabel: t("Xóa job", "Delete job"),
      run: () => void flowRequest(`/api/flow/jobs/${id}`, { method: "DELETE" })
        .then(() => setJobs((current) => current.filter((item) => item.id !== id)))
        .catch((error) => setApiError(error instanceof Error ? error.message : String(error))),
    });
  };
  const cancelAllJobs = () => {
    const activeCount = jobs.filter((job) => job.status === "queued" || job.status === "processing").length;
    if (!activeCount) return;
    setConfirmAction({
      message: t(`Hủy ${activeCount} job đang chờ/chạy?`, `Cancel ${activeCount} queued/running jobs?`),
      confirmLabel: t("Hủy tất cả", "Cancel all"),
      run: () => void flowRequest<{ jobs: Array<Record<string, unknown>> }>("/api/flow/jobs/cancel-all", { method: "POST" })
        .then(({ jobs: rows }) => {
          setJobs(normalizeFlowJobs(rows, accounts));
          setApiError("");
        })
        .catch((error) => setApiError(error instanceof Error ? error.message : String(error))),
    });
  };
  const deleteAllJobs = () => {
    if (!jobs.length) return;
    setConfirmAction({
      message: t(`Xóa toàn bộ ${jobs.length} job khỏi hàng đợi?`, `Delete all ${jobs.length} jobs from the queue?`),
      confirmLabel: t("Xóa tất cả", "Delete all"),
      run: () => void flowRequest<{ jobs: Array<Record<string, unknown>> }>("/api/flow/jobs", { method: "DELETE" })
        .then(({ jobs: rows }) => {
          setJobs(normalizeFlowJobs(rows, accounts));
          setApiError("");
        })
        .catch((error) => setApiError(error instanceof Error ? error.message : String(error))),
    });
  };
  const setDefaultAccount = (id: string) => {
    const selected = accounts.find((account) => account.id === id);
    if (selected) {
      setSettings((current) => ({ ...current, account: selected.label }));
      void flowRequest(`/api/flow/accounts/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: selected.label,
          email: selected.email,
          plan: selected.plan,
          projectId: selected.projectId || "",
          isDefault: true,
        }),
      }).catch((error) =>
        setApiError(error instanceof Error ? error.message : String(error)),
      );
    }
  };
  const connectAccount = (account: FlowAccount) =>
    void flowRequest<FlowAccount>(`/api/flow/accounts/${account.id}/connect`, {
      method: "POST",
    }).then((connected) => setAccounts((current) => current.map((item) => item.id === connected.id ? connected : item)))
      .catch((error) => setApiError(error instanceof Error ? error.message : String(error)));
  const revealOutput = (jobId: string, outputIndex: number) =>
    void flowRequest(`/api/flow/jobs/${jobId}/outputs/${outputIndex}/reveal`, {
      method: "POST",
    }).catch((error) =>
      setApiError(error instanceof Error ? error.message : String(error)),
    );
  const pickOutputFolder = async (): Promise<
    FileSystemDirectoryHandle | "cancelled" | null
  > => {
    try {
      if (!isDesktopApp) {
        const pickerWindow = window as DirectoryPickerWindow;
        if (!pickerWindow.showDirectoryPicker) {
          throw new Error(t("Trình duyệt này không hỗ trợ chọn thư mục ghi file.", "This browser does not support writable folder selection."));
        }
        const directory = await pickerWindow.showDirectoryPicker({
          id: "zm-flow-output",
          mode: "readwrite",
          startIn: "downloads",
        });
        webOutputDirectoryRef.current = directory;
        setWebOutputDirectoryName(directory.name);
        setSettings((current) => ({ ...current, autoDownload: true }));
        setApiError("");
        return directory;
      }
      const result = await flowRequest<{ path?: string }>(
        "/api/system/pick-folder",
        { method: "POST" },
      );
      if (result.path) {
        setSettings((current) => ({ ...current, outputDir: result.path! }));
      }
      return null;
    } catch (error) {
      if (
        error &&
        typeof error === "object" &&
        "name" in error &&
        error.name === "AbortError"
      ) {
        setApiError("");
        return "cancelled";
      }
      setApiError(error instanceof Error ? error.message : String(error));
      return null;
    }
  };

  const clearLogs = () => {
    setConfirmAction({
      message: t("Xóa toàn bộ log Flow?", "Clear all Flow logs?"),
      confirmLabel: t("Xóa log", "Clear logs"),
      run: () => void flowRequest("/api/flow/logs", { method: "DELETE" })
        .then(() => setLogs([]))
        .catch((error) => setApiError(error instanceof Error ? error.message : String(error))),
    });
  };
  const copyLogs = async () => {
    const text = logs
      .map((entry) => {
        const context = [
          entry.jobId ? `job=${entry.jobId}` : "",
          entry.accountId ? `account=${entry.accountId}` : "",
        ]
          .filter(Boolean)
          .join(" ");
        const details = Object.keys(entry.details || {}).length
          ? ` details=${JSON.stringify(entry.details)}`
          : "";
        return `[${new Date(entry.createdAt * 1000).toISOString()}] [${entry.level.toUpperCase()}] ${entry.event}${context ? ` ${context}` : ""}${entry.message ? ` - ${entry.message}` : ""}${details}`;
      })
      .join("\n");
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        if (!document.execCommand("copy")) throw new Error("COPY_FAILED");
        textarea.remove();
      }
      setLogsCopied(true);
      window.setTimeout(() => setLogsCopied(false), 1800);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error));
    }
  };
  const logEventText = (event: string) => {
    const labels: Record<string, string> = {
      account_connecting: t("Đang kết nối tài khoản", "Connecting account"),
      account_connected: t("Đã kết nối tài khoản", "Account connected"),
      account_connect_failed: t(
        "Kết nối tài khoản thất bại",
        "Account connection failed",
      ),
      job_queued: t("Đã thêm vào hàng đợi", "Added to queue"),
      job_started: t("Bắt đầu xử lý", "Processing started"),
      browser_ready: t("Session trình duyệt sẵn sàng", "Browser session ready"),
      generation_submitted: t("Đã gửi yêu cầu tạo", "Generation submitted"),
      output_downloaded: t("Đã tải output", "Output downloaded"),
      job_completed: t("Job hoàn thành", "Job completed"),
      job_cancel_requested: t("Đã yêu cầu hủy", "Cancellation requested"),
      job_cancelled: t("Job đã hủy", "Job cancelled"),
      job_retry: t("Đang chạy lại job", "Retrying job"),
      job_failed: t("Job gặp lỗi", "Job failed"),
    };
    return labels[event] || event;
  };

  return (
    <main className="flow-page">
      <aside
        className={`flow-rail ${railOpen ? "is-open" : ""}`}
        aria-label={t("Điều hướng Flow", "Flow navigation")}
      >
        <button
          className="flow-rail-toggle"
          type="button"
          onClick={() => setRailOpen((open) => !open)}
          aria-label={
            railOpen
              ? t("Thu gọn menu", "Collapse menu")
              : t("Mở rộng menu", "Expand menu")
          }
          aria-expanded={railOpen}
        >
          <span />
          <span />
          <span />
        </button>
        <nav>
          {(
            [
              ["createImage", IconImage, t("Tạo ảnh", "Create image")],
              ["createVideo", IconVideo, t("Tạo video", "Create video")],
              ["queue", IconBatch, t("Hàng đợi", "Queue")],
              ["history", IconClock, t("Lịch sử", "History")],
              ["accounts", IconGear, t("Tài khoản", "Accounts")],
              ["logs", IconLog, t("Log", "Logs")],
              ["help", IconBook, t("Trợ giúp", "Help")],
            ] as const
          ).map(([id, Icon, label]) => (
            <button
              key={id}
              type="button"
              className={
                ((id === "createImage" &&
                  tab === "create" &&
                  createKind === "image") ||
                (id === "createVideo" &&
                  tab === "create" &&
                  createKind === "video") ||
                id === tab ||
                id === utilityView
                  ? "is-active "
                  : "") + (id === "accounts" || id === "help" ? "is-muted" : "")
              }
              onClick={() => activateRail(id)}
              title={label}
              aria-label={label}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="flow-rail-credit">
          <strong>
            {displayedAccount?.credits != null
              ? displayedAccount.credits.toLocaleString()
              : "—"}
          </strong>
          <span>
            {displayedAccount?.credits != null
              ? t("credits còn lại", "credits left")
              : t("Chưa đồng bộ", "Not synced")}
          </span>
        </div>
      </aside>
      <section className="flow-workspace">
        <div className="flow-heading">
          <BackTitle onBack={onBack}>
            <span className="flow-page-title">
              Flow (Veo 3)
              <small>
                {t(
                  "Tạo ảnh và video bằng tài khoản Google Pro/Ultra.",
                  "Create images and videos with Google Pro/Ultra accounts.",
                )}
              </small>
            </span>
          </BackTitle>
          <div
            className={`flow-api-state ${backendReady ? "is-online" : "is-offline"}`}
            role="status"
          >
            <span />
            {backendReady
              ? t("Backend Flow đã kết nối", "Flow backend connected")
              : t("Backend Flow chưa sẵn sàng", "Flow backend unavailable")}
            {apiError && <small>{apiError}</small>}
          </div>
        </div>
        {utilityView === "accounts" && (
          <section className="flow-accounts">
            <header>
              <div>
                <h2>{t("Tài khoản Google Flow", "Google Flow accounts")}</h2>
                <p>
                  {t(
                    "Quản lý Chrome profile và phiên đăng nhập riêng cho từng tài khoản Pro/Ultra.",
                    "Manage a separate Chrome profile and login session for each Pro/Ultra account.",
                  )}
                </p>
              </div>
              <button
                type="button"
                className="flow-account-add"
                onClick={addAccount}
              >
                + {t("Thêm tài khoản", "Add account")}
              </button>
            </header>
            {editingAccount && (
              <form
                className="flow-account-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  saveAccount();
                }}
              >
                <div>
                  <h3>
                    {editingAccount === "new"
                      ? t("Thêm tài khoản", "Add account")
                      : t("Sửa tài khoản", "Edit account")}
                  </h3>
                  <p>
                    {t(
                      "Thông tin dùng để liên kết Chrome profile và session Flow.",
                      "Details used to bind the Chrome profile and Flow session.",
                    )}
                  </p>
                </div>
                <label>
                  <span>{t("Tên hiển thị", "Display name")}</span>
                  <input
                    autoFocus
                    value={accountDraft.label}
                    onChange={(event) =>
                      setAccountDraft((current) => ({
                        ...current,
                        label: event.target.value,
                      }))
                    }
                    placeholder="Ultra 01"
                  />
                </label>
                <label>
                  <span>Email Google</span>
                  <input
                    type="email"
                    value={accountDraft.email}
                    onChange={(event) =>
                      setAccountDraft((current) => ({
                        ...current,
                        email: event.target.value,
                      }))
                    }
                    placeholder="name@gmail.com"
                  />
                </label>
                <FlowSelect
                  label={t("Gói tài khoản", "Account plan")}
                  value={accountDraft.plan}
                  onChange={(plan) =>
                    setAccountDraft((current) => ({
                      ...current,
                      plan: plan as FlowAccount["plan"],
                    }))
                  }
                  options={["Pro", "Ultra"]}
                />
                <footer>
                  <button type="button" onClick={() => setEditingAccount(null)}>
                    {t("Hủy", "Cancel")}
                  </button>
                  <button
                    type="submit"
                    disabled={
                      !accountDraft.label.trim() || !accountDraft.email.trim()
                    }
                  >
                    {t("Lưu", "Save")}
                  </button>
                </footer>
              </form>
            )}
            <div className="flow-account-grid">
              {accounts.map((account) => (
                <article
                  key={account.id}
                  className={account.isDefault ? "is-default" : ""}
                >
                  <div className="flow-account-head">
                    <span>{account.plan}</span>
                    <mark className={account.status}>
                      {account.status === "online"
                        ? t("Online", "Online")
                        : account.status === "connecting"
                          ? t("Đang kết nối", "Connecting")
                          : t("Cần kết nối lại", "Reconnect needed")}
                    </mark>
                  </div>
                  <h3>
                    {account.label}
                    {account.isDefault && (
                      <small>{t("Mặc định", "Default")}</small>
                    )}
                  </h3>
                  <p>{account.email}</p>
                  <div className="flow-account-credits">
                    <strong>
                      {account.credits != null
                        ? account.credits.toLocaleString()
                        : "—"}
                    </strong>
                    <span>
                      {account.credits != null
                        ? t("credits còn lại", "credits left")
                        : t("Chưa đồng bộ credits", "Credits not synced")}
                    </span>
                    {account.credits != null && account.used > 0 && (
                      <>
                        <i>
                          <em
                            style={{
                              width: `${Math.max(8, 100 - account.used)}%`,
                            }}
                          />
                        </i>
                        <small>
                          {account.used}% {t("đã dùng", "used")}
                        </small>
                      </>
                    )}
                  </div>
                  <footer>
                    {account.isDefault ? (
                      <span>{t("Đang dùng mặc định", "Current default")}</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setDefaultAccount(account.id)}
                      >
                        {t("Đặt mặc định", "Set default")}
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={account.status === "connecting"}
                      onClick={() => connectAccount(account)}
                    >
                      {account.status === "connecting"
                        ? t("Đang mở Chrome…", "Opening Chrome…")
                        : account.status === "online"
                          ? t("Đăng nhập lại", "Reconnect")
                          : t("Kết nối", "Connect")}
                    </button>
                    <button type="button" onClick={() => editAccount(account)}>
                      {t("Sửa", "Edit")}
                    </button>
                    <button
                      type="button"
                      className="is-danger"
                      disabled={account.isDefault}
                      onClick={() => deleteAccount(account)}
                    >
                      {t("Xóa", "Delete")}
                    </button>
                  </footer>
                </article>
              ))}
            </div>
            <aside className="flow-account-note">
              <IconGear size={18} />
              {t(
                "Mỗi tài khoản dùng Chrome profile và hàng đợi riêng. Bấm Kết nối rồi đăng nhập Google trong cửa sổ Chrome.",
                "Each account uses its own Chrome profile and queue. Click Connect, then sign in to Google in the Chrome window.",
              )}
            </aside>
          </section>
        )}
        {utilityView === "help" && (
          <section className="flow-empty-panel">
            <IconBook size={26} />
            <h2>{t("Trợ giúp Flow", "Flow help")}</h2>
            <p>
              {t(
                "Chọn Tài khoản để thêm hoặc kiểm tra session Google Flow.",
                "Open Accounts to add or check a Google Flow session.",
              )}
            </p>
          </section>
        )}
        {!utilityView && (
          <div className="flow-tabs" role="tablist">
            {(
              [
                ["create", t("Tạo nội dung", "Create")],
                ["queue", t("Hàng đợi", "Queue")],
                ["history", t("Lịch sử", "History")],
                ["logs", t("Log", "Logs")],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                className={tab === id ? "is-active" : ""}
                onClick={() => setTab(id)}
              >
                {id === "create" ? (
                  <IconVideo size={16} />
                ) : id === "queue" ? (
                  <IconBatch size={16} />
                ) : id === "history" ? (
                  <IconClock size={16} />
                ) : (
                  <IconBook size={16} />
                )}
                {label}
              </button>
            ))}
          </div>
        )}
        {!utilityView && showCreate && (
          <div className="flow-create-grid">
            <section className="flow-card flow-prompt-card">
              {createKind === "image" && (
                <div
                  className="flow-image-modes"
                  role="tablist"
                  aria-label={t("Chế độ tạo ảnh", "Image generation mode")}
                >
                  {(
                    [
                      ["text", t("Text → Ảnh", "Text → Image")],
                      ["edit", t("Ảnh → Ảnh", "Image → Image")],
                      ["reference", t("Tham chiếu → Ảnh", "Reference → Image")],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      role="tab"
                      aria-selected={imageMode === id}
                      className={imageMode === id ? "is-active" : ""}
                      onClick={() => {
                        setImageMode(id);
                        setSourceFiles([]);
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {createKind === "image" && imageMode !== "text" && (
                <div className="flow-source-row">
                  <div>
                    <IconImage size={20} />
                    <span>
                      <b>
                        {imageMode === "edit"
                          ? t("Ảnh nguồn", "Source image")
                          : t("Ảnh tham chiếu", "Reference images")}
                      </b>
                      <small>
                        {imageMode === "edit"
                          ? t(
                              "Một ảnh để chỉnh sửa hoặc biến thể",
                              "One image to edit or create variants",
                            )
                          : t(
                              "Tối đa 3 ảnh giữ nhân vật/phong cách",
                              "Up to 3 images for subject/style consistency",
                            )}
                      </small>
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => sourceRef.current?.click()}
                  >
                    {t("Chọn ảnh", "Choose images")}
                  </button>
                  <input
                    ref={sourceRef}
                    type="file"
                    hidden
                    accept="image/png,image/jpeg,image/webp"
                    multiple={imageMode === "reference"}
                    onChange={(event) =>
                      setSourceFiles(
                        Array.from(event.target.files || []).slice(
                          0,
                          imageMode === "reference" ? 3 : 1,
                        ),
                      )
                    }
                  />
                  {sourceFiles.length > 0 && (
                    <p>
                      {sourceFiles.map((file) => (
                        <mark key={`${file.name}-${file.lastModified}`}>
                          {file.name}
                          <button
                            type="button"
                            onClick={() =>
                              setSourceFiles((current) =>
                                current.filter((item) => item !== file),
                              )
                            }
                            aria-label={t(
                              `Bỏ ${file.name}`,
                              `Remove ${file.name}`,
                            )}
                          >
                            ×
                          </button>
                        </mark>
                      ))}
                    </p>
                  )}
                </div>
              )}
              <div className="flow-card-title">
                <b>
                  {t(
                    `1. Prompt ${createKind === "video" ? "video" : "ảnh"}`,
                    `1. ${createKind === "video" ? "Video" : "Image"} prompt`,
                  )}
                </b>
                <div className="flow-prompt-actions">
                  <span>
                    {promptCount} {t("prompt", "prompts")}
                  </span>
                  <button type="button" onClick={() => void pastePrompt()}>
                    {t("Dán", "Paste")}
                  </button>
                  <button
                    type="button"
                    className="is-danger"
                    disabled={!prompt}
                    onClick={() => {
                      setPrompt("");
                      setPromptInputType("prompt");
                      setImportName("");
                    }}
                  >
                    {t("Xóa", "Clear")}
                  </button>
                </div>
              </div>
              <textarea
                value={prompt}
                onChange={(event) => {
                  setPrompt(event.target.value);
                  setPromptInputType("prompt");
                  setImportName("");
                }}
                maxLength={8000}
                placeholder={
                  createKind === "video"
                    ? t(
                        "Mô tả cảnh, chuyển động camera và âm thanh mong muốn.",
                        "Describe the scene, camera movement, and desired audio.",
                      )
                    : t(
                        "Mô tả chủ thể, bối cảnh, ánh sáng và phong cách ảnh.",
                        "Describe the subject, setting, lighting, and image style.",
                      )
                }
              />
              <div className="flow-prompt-foot">
                <span>
                  {t(
                    "Mỗi đoạn cách nhau một dòng trống.",
                    "One blank line separates each prompt.",
                  )}
                </span>
                <span>{prompt.length} / 8000</span>
              </div>
              <div className="flow-import">
                <div className="flow-import-row">
                  <button type="button" onClick={() => fileRef.current?.click()}>
                    <span className="flow-paperclip">⌕</span>
                    {t("Nhập TXT / CSV / JSON", "Import TXT / CSV / JSON")}
                  </button>
                  <span>
                    {t(
                      "TXT: mỗi đoạn một prompt · CSV/JSON: lấy cột prompt.",
                      "TXT: one prompt per block · CSV/JSON: reads the prompt field.",
                    )}
                  </span>
                </div>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".txt,.csv,.json,text/plain,application/json"
                  onChange={(event) => importPrompts(event.target.files?.[0])}
                />
                {importName && (
                  <small>
                    {t("Đã thêm", "Added")}: {importName}
                  </small>
                )}
              </div>
            </section>
            <section className="flow-card flow-settings-card">
              <div className="flow-card-title">
                <b>{t("2. Cài đặt nhanh", "2. Quick settings")}</b>
                <button
                  className="flow-text-button"
                  type="button"
                  onClick={() => setAdvancedOpen((open) => !open)}
                  aria-expanded={advancedOpen}
                >
                  <IconGear size={15} />
                  {advancedOpen
                    ? t("Thu gọn", "Collapse")
                    : t("Nâng cao", "Advanced")}
                </button>
              </div>
              <div className="flow-settings-grid">
                <FlowSelect
                  label={t("Model", "Model")}
                  value={settings.model}
                  onChange={(model) =>
                    setSettings((current) => ({ ...current, model }))
                  }
                  options={
                    createKind === "video"
                      ? [...FLOW_VIDEO_MODELS]
                      : [...FLOW_IMAGE_MODELS]
                  }
                />
                <FlowSelect
                  label={t("Tỷ lệ", "Ratio")}
                  value={settings.ratio}
                  onChange={(ratio) =>
                    setSettings((current) => ({ ...current, ratio }))
                  }
                  options={
                    createKind === "video"
                      ? ["16:9", "9:16"]
                      : ["1:1", "16:9", "9:16", "4:3", "3:4"]
                  }
                />
                {createKind === "video" ? (
                  <FlowSelect
                    label={t("Thời lượng", "Duration")}
                    value={settings.duration}
                    onChange={(duration) =>
                      setSettings((current) => ({ ...current, duration }))
                    }
                    options={["8", "10"]}
                    suffix={t(" giây", " sec")}
                  />
                ) : (
                  <FlowSelect
                    label={t("Độ phân giải", "Resolution")}
                    value={settings.resolution}
                    onChange={(resolution) =>
                      setSettings((current) => ({ ...current, resolution }))
                    }
                    options={["1K", "2K", "4K"]}
                  />
                )}
                <label>
                  <span>
                    {createKind === "video"
                      ? t("Số video", "Videos")
                      : t("Số ảnh", "Images")}
                  </span>
                  <div className="flow-counter">
                    <button
                      type="button"
                      onClick={() =>
                        setSettings((current) => ({
                          ...current,
                          count: Math.max(1, current.count - 1),
                        }))
                      }
                      aria-label={t("Giảm số lượng", "Decrease quantity")}
                    >
                      −
                    </button>
                    <strong>{settings.count}</strong>
                    <button
                      type="button"
                      onClick={() =>
                        setSettings((current) => ({
                          ...current,
                          count: Math.min(4, current.count + 1),
                        }))
                      }
                      aria-label={t("Tăng số lượng", "Increase quantity")}
                    >
                      +
                    </button>
                  </div>
                </label>
                <FlowSelect
                  label={t("Tài khoản", "Account")}
                  value={settings.account}
                  onChange={(account) =>
                    setSettings((current) => ({ ...current, account }))
                  }
                  options={accounts.map((account) => account.label)}
                  online
                />
              </div>
              {advancedOpen && (
                <div className="flow-advanced">
                  <FlowSelect
                    label={t("Chất lượng", "Quality")}
                    value={settings.quality}
                    onChange={(quality) =>
                      setSettings((current) => ({ ...current, quality }))
                    }
                    options={["Standard", "High"]}
                  />
                  <label>
                    <span>
                      {t(
                        "Seed (để trống = tự động)",
                        "Seed (blank = automatic)",
                      )}
                    </span>
                    <input
                      value={settings.seed}
                      inputMode="numeric"
                      placeholder={t("Tự động", "Automatic")}
                      onChange={(event) =>
                        setSettings((current) => ({
                          ...current,
                          seed: event.target.value.replace(/\D/g, ""),
                        }))
                      }
                    />
                  </label>
                  <FlowSelect
                    label={t("Định dạng lưu", "Output format")}
                    value={settings.format}
                    onChange={(format) =>
                      setSettings((current) => ({ ...current, format }))
                    }
                    options={
                      createKind === "image" ? ["PNG", "JPG", "WebP"] : ["MP4"]
                    }
                  />
                  <label>
                    <span>{t("Tiền tố tên file", "Filename prefix")}</span>
                    <input
                      value={settings.filePrefix}
                      onChange={(event) =>
                        setSettings((current) => ({
                          ...current,
                          filePrefix: event.target.value,
                        }))
                      }
                    />
                  </label>
                  {createKind === "image" && imageMode !== "text" && (
                    <label className="flow-range">
                      <span>
                        {t("Mức bám ảnh tham chiếu", "Reference strength")} ·{" "}
                        {settings.referenceStrength}%
                      </span>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={settings.referenceStrength}
                        onChange={(event) =>
                          setSettings((current) => ({
                            ...current,
                            referenceStrength: Number(event.target.value),
                          }))
                        }
                      />
                    </label>
                  )}
                  <label className="flow-check flow-enhance">
                    <input
                      type="checkbox"
                      checked={settings.enhancePrompt}
                      onChange={(event) =>
                        setSettings((current) => ({
                          ...current,
                          enhancePrompt: event.target.checked,
                        }))
                      }
                    />
                    {t("Tự động làm rõ prompt", "Automatically enhance prompt")}
                  </label>
                </div>
              )}
              <div className="flow-output-row">
                <OutputFolderField isDesktopApp={isDesktopApp} value={settings.outputDir} onChange={(outputDir) => setSettings((current) => ({ ...current, outputDir }))} onChoose={() => void pickOutputFolder()} onSave={() => localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))} defaultPath={t("Mặc định: Downloads/ZM_AIO_TOOL/flow", "Default: Downloads/ZM_AIO_TOOL/flow")} label={t("3. Thư mục kết quả", "3. Output folder")} selectedRootName={webOutputDirectoryName ? `${webOutputDirectoryName}/flow` : ""} webFolderOnly />
                {!isDesktopApp && (
                  <label className="flow-check">
                    <input
                      type="checkbox"
                      checked={settings.autoDownload}
                      onChange={(event) =>
                        setSettings((current) => ({
                          ...current,
                          autoDownload: event.target.checked,
                        }))
                      }
                    />
                    {t("Tự động tải về khi hoàn thành", "Auto-download when completed")}
                  </label>
                )}
              </div>
              <div className={`flow-create-actions ${createKind === "video" ? "has-preview" : ""}`}>
                {createKind === "video" && (
                  <button
                    type="button"
                    className="flow-preview-latest"
                    disabled={!latestCompletedVideo}
                    onClick={() =>
                      latestCompletedVideo &&
                      setPreview({ job: latestCompletedVideo, outputIndex: 0 })
                    }
                  >
                    <IconPlay size={16} />
                    {latestCompletedVideo
                      ? t("Xem trước video", "Preview video")
                      : t("Chưa có video", "No video yet")}
                  </button>
                )}
                <button
                  type="button"
                  className="flow-generate"
                  onClick={() => void createFlowJobs()}
                >
                  <IconPlay size={17} />
                  {createKind === "video"
                    ? t("TẠO VIDEO", "CREATE VIDEO")
                    : t("TẠO ẢNH", "CREATE IMAGES")}
                  <small>
                    {t(
                      "Gửi qua Chrome profile của tài khoản đã chọn",
                      "Sent through the selected account Chrome profile",
                    )}
                  </small>
                </button>
              </div>
            </section>
          </div>
        )}
        {!utilityView && (tab === "create" || tab === "queue") && (
          <section className="flow-card flow-queue-card">
            <div className="flow-card-title">
              <b>{t(`Hàng đợi (${jobs.length})`, `Queue (${jobs.length})`)}</b>
              <div className="flow-queue-tools">
                <button className="flow-text-button" type="button" onClick={() => setTab("queue")}>{t("Xem tất cả", "View all")}</button>
                <button className="flow-text-button" type="button" disabled={!jobs.some((job) => job.status === "queued" || job.status === "processing")} onClick={cancelAllJobs}>{t("Hủy tất cả", "Cancel all")}</button>
                <button className="flow-text-button is-danger" type="button" disabled={!jobs.length} onClick={deleteAllJobs}>{t("Xóa tất cả", "Delete all")}</button>
              </div>
            </div>
            <div className="flow-queue-list">
              {jobs.map((job) => (
                <article
                  key={job.id}
                  className={`flow-queue-job flow-queue-job--${job.status}`}
                >
                  <button
                    className="flow-job-thumb"
                    type="button"
                    disabled={!job.outputs?.length}
                    onClick={() =>
                      job.outputs?.length && setPreview({ job, outputIndex: 0 })
                    }
                    aria-label={
                      job.outputs?.length
                        ? t("Xem trước output", "Preview output")
                        : t("Output chưa sẵn sàng", "Output not ready")
                    }
                  >
                    {job.outputs?.length ? (
                      job.kind === "video" ? (
                        <video
                          src={`/api/flow/jobs/${job.id}/outputs/0`}
                          muted
                          playsInline
                          preload="metadata"
                        />
                      ) : (
                        <img
                          src={`/api/flow/jobs/${job.id}/outputs/0`}
                          alt=""
                          loading="lazy"
                        />
                      )
                    ) : job.kind === "video" ? (
                      <IconPlay size={15} />
                    ) : (
                      <IconImage size={17} />
                    )}
                  </button>
                  <div>
                    <strong>
                      {String(job.index).padStart(3, "0")} · {job.prompt}
                    </strong>
                    <span>
                      {job.kind === "video"
                        ? `${job.settings.model} · ${job.settings.ratio} · ${job.settings.duration}s`
                        : `${job.settings.model} · ${job.settings.ratio} · ${job.settings.resolution}`}{" "}
                      · {job.account}
                    </span>
                    <div className="flow-job-progress">
                      <i>
                        <em style={{ width: `${job.progress}%` }} />
                      </i>
                      <small>{job.progress}%</small>
                    </div>
                    {job.error && (
                      <small className="flow-job-error">{jobErrorText(job.error)}</small>
                    )}
                  </div>
                  <aside>
                    <mark>{statusText(job.status)}</mark>
                    <div className="flow-job-actions">
                      {(job.status === "queued" ||
                        job.status === "processing") && (
                        <button type="button" onClick={() => cancelJob(job.id)}>
                          {t("Hủy", "Cancel")}
                        </button>
                      )}
                      {(job.status === "failed" ||
                        job.status === "cancelled") && (
                        <button type="button" onClick={() => retryJob(job.id)}>
                          {t("Chạy lại", "Retry")}
                        </button>
                      )}
                      <button
                        type="button"
                        className="is-danger"
                        onClick={() => deleteJob(job.id)}
                      >
                        {t("Xóa", "Delete")}
                      </button>
                    </div>
                    {job.outputs?.length ? (
                      <div className="flow-queue-outputs">
                        {job.outputs.map((_output, outputIndex) => (
                          <span key={outputIndex}>
                            <button
                              type="button"
                              onClick={() => setPreview({ job, outputIndex })}
                            >
                              {t("Xem trước", "Preview")}{" "}
                              {job.outputs!.length > 1 ? outputIndex + 1 : ""}
                            </button>
                            {isDesktopApp ? (
                              <button
                                type="button"
                                onClick={() =>
                                  revealOutput(job.id, outputIndex)
                                }
                              >
                                {t("Mở thư mục", "Open folder")}
                              </button>
                            ) : (
                              <a
                                href={`/api/flow/jobs/${job.id}/outputs/${outputIndex}?download=1`}
                                download
                              >
                                {t("Tải về", "Download")}
                              </a>
                            )}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </aside>
                </article>
              ))}
            </div>
          </section>
        )}
        {!utilityView && tab === "create" && (
          <section className="flow-card flow-results">
            <div className="flow-card-title">
              <b>{t("Kết quả gần đây", "Recent results")}</b>
              <button
                className="flow-text-button"
                type="button"
                onClick={() => setTab("history")}
              >
                {t("Xem tất cả", "View all")}
              </button>
            </div>
            <div className="flow-result-grid">
              {jobs
                .filter(
                  (job) => job.kind === createKind && job.status === "done",
                )
                .slice(0, 4)
                .map((job) => (
                  <article key={job.id}>
                    <button
                      className="flow-result-thumb"
                      type="button"
                      onClick={() => setPreview({ job, outputIndex: 0 })}
                      aria-label={t("Xem trước output", "Preview output")}
                    >
                      {job.kind === "video" ? (
                        <video
                          src={`/api/flow/jobs/${job.id}/outputs/0`}
                          muted
                          playsInline
                          preload="metadata"
                        />
                      ) : (
                        <img
                          src={`/api/flow/jobs/${job.id}/outputs/0`}
                          alt={job.prompt}
                          loading="lazy"
                        />
                      )}
                      <mark>{t("Hoàn thành", "Completed")}</mark>
                    </button>
                    <strong>{job.prompt}</strong>
                    <span>{job.id}</span>
                    <p>
                      {job.outputs?.length || 0}{" "}
                      {job.kind === "video"
                        ? t("video", "videos")
                        : t("ảnh", "images")}
                    </p>
                    <footer>
                      {job.outputs?.map((_output, outputIndex) => (
                        <span className="flow-output-actions" key={outputIndex}>
                          <button
                            type="button"
                            onClick={() => setPreview({ job, outputIndex })}
                          >
                            {t("Xem trước", "Preview")}
                          </button>
                          {isDesktopApp ? (
                            <button
                              type="button"
                              onClick={() => revealOutput(job.id, outputIndex)}
                            >
                              {t("Mở thư mục", "Open folder")}
                            </button>
                          ) : (
                            <a
                              href={`/api/flow/jobs/${job.id}/outputs/${outputIndex}?download=1`}
                              download
                            >
                              <IconDownload size={15} />
                              {t("Tải về", "Download")}
                            </a>
                          )}
                        </span>
                      ))}
                    </footer>
                  </article>
                ))}
              {!jobs.some(
                (job) => job.kind === createKind && job.status === "done",
              ) && (
                <div className="flow-results-empty">
                  {t(
                    "Chưa có kết quả thật. Kết quả tải xong sẽ xuất hiện tại đây.",
                    "No real results yet. Completed downloads will appear here.",
                  )}
                </div>
              )}
            </div>
          </section>
        )}
        {!utilityView && (tab === "history" || tab === "queue") && (
          <section className="flow-card flow-history">
            <div className="flow-card-title">
              <b>{t("Lịch sử nhiệm vụ", "Task history")}</b>
              <span>{t("Dữ liệu backend", "Backend data")}</span>
            </div>
            <div className="flow-history-scroll">
              <table>
                <thead>
                  <tr>
                    {[
                      t("Thời gian", "Time"),
                      t("Loại", "Type"),
                      t("Input", "Input"),
                      t("Prompt", "Prompt"),
                      t("Model", "Model"),
                      t("Tài khoản", "Account"),
                      t("TT", "Status"),
                      t("Output", "Output"),
                      t("Tác vụ", "Actions"),
                    ].map((label) => (
                      <th key={label}>{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job, index) => (
                    <tr key={job.id}>
                      <td>24/08 · 14:{30 - index * 4}</td>
                      <td>
                        <mark>
                          {job.kind === "video"
                            ? t("Video", "Video")
                            : t("Ảnh", "Image")}
                        </mark>
                      </td>
                      <td>
                        <mark>
                          {job.inputType === "prompt"
                            ? t("Nhập tay", "Manual")
                            : job.inputType.toUpperCase()}
                        </mark>
                      </td>
                      <td title={job.prompt}>{job.prompt}</td>
                      <td title={job.settings.model}>
                        {job.settings.model}
                      </td>
                      <td title={job.account}>{job.account}</td>
                      <td>
                        <mark className={`flow-status-${job.status}`}>
                          {statusText(job.status)}
                        </mark>
                      </td>
                      <td>
                        {job.outputs?.length
                          ? job.outputs.map((_output, outputIndex) => (
                              <span
                                className="flow-output-actions"
                                key={outputIndex}
                              >
                                <button
                                  type="button"
                                  onClick={() =>
                                    setPreview({ job, outputIndex })
                                  }
                                >
                                  {t("Xem", "View")}{" "}
                                  {(job.outputs?.length || 0) > 1
                                    ? outputIndex + 1
                                    : ""}
                                </button>
                                {isDesktopApp ? (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      revealOutput(job.id, outputIndex)
                                    }
                                  >
                                    {t("Mở", "Open")}
                                  </button>
                                ) : (
                                  <a
                                    href={`/api/flow/jobs/${job.id}/outputs/${outputIndex}?download=1`}
                                    download
                                  >
                                    {t("Tải", "Save")}
                                  </a>
                                )}
                              </span>
                            ))
                          : "—"}
                      </td>
                      <td>
                        <div className="flow-table-actions">
                          {job.status === "queued" ||
                          job.status === "processing" ? (
                            <button
                              type="button"
                              onClick={() => cancelJob(job.id)}
                            >
                              {t("Hủy", "Cancel")}
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => retryJob(job.id)}
                            >
                              {t("Chạy lại", "Retry")}
                            </button>
                          )}
                          <button
                            type="button"
                            className="is-danger"
                            onClick={() => deleteJob(job.id)}
                          >
                            {t("Xóa", "Delete")}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        {!utilityView && tab === "logs" && (
          <section className="flow-card flow-logs">
            <div className="flow-card-title">
              <div>
                <b>{t("Log hoạt động Flow", "Flow activity logs")}</b>
                <span>
                  {t(
                    "Theo dõi tạo nội dung, tải output và lỗi backend",
                    "Track generation, output downloads, and backend errors",
                  )}
                </span>
              </div>
              <div className="flow-log-actions">
                <button
                  type="button"
                  className="flow-log-copy"
                  onClick={() => void copyLogs()}
                  disabled={!logs.length}
                >
                  {logsCopied
                    ? t("Đã sao chép", "Copied")
                    : t("Sao chép log", "Copy logs")}
                </button>
                <button
                  type="button"
                  className="flow-log-clear"
                  onClick={clearLogs}
                  disabled={!logs.length}
                >
                  {t("Xóa log", "Clear logs")}
                </button>
              </div>
            </div>
            {logs.length ? (
              <div className="flow-log-list" role="log" aria-live="polite">
                {logs.map((entry) => {
                  const account = accounts.find(
                    (item) => item.id === entry.accountId,
                  );
                  const detailText = Object.keys(entry.details || {}).length
                    ? JSON.stringify(entry.details)
                    : "";
                  return (
                    <article
                      className={`flow-log-row is-${entry.level}`}
                      key={entry.id}
                    >
                      <time>
                        {new Date(entry.createdAt * 1000).toLocaleString(
                          locale === "vi" ? "vi-VN" : "en-US",
                        )}
                      </time>
                      <mark>{entry.level.toUpperCase()}</mark>
                      <div className="flow-log-message">
                        <strong>{logEventText(entry.event)}</strong>
                        {entry.message && <p>{entry.message}</p>}
                        {detailText && <code>{detailText}</code>}
                      </div>
                      <div className="flow-log-context">
                        {entry.jobId && <span>Job: {entry.jobId}</span>}
                        {entry.accountId && (
                          <span>
                            {t("Tài khoản", "Account")}:{" "}
                            {account?.label || entry.accountId}
                          </span>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="flow-logs-empty">
                <IconBook size={24} />
                <b>{t("Chưa có log Flow", "No Flow logs yet")}</b>
                <span>
                  {t(
                    "Log sẽ xuất hiện khi kết nối tài khoản hoặc chạy job.",
                    "Logs appear when an account connects or a job runs.",
                  )}
                </span>
              </div>
            )}
          </section>
        )}
        {confirmAction && (
          <div
            className="flow-preview-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setConfirmAction(null);
            }}
          >
            <section className="flow-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="flow-confirm-title">
              <header>
                <strong id="flow-confirm-title">{t("Xác nhận thao tác", "Confirm action")}</strong>
                <button type="button" onClick={() => setConfirmAction(null)} aria-label={t("Đóng", "Close")}>×</button>
              </header>
              <p>{confirmAction.message}</p>
              <footer>
                <button type="button" onClick={() => setConfirmAction(null)}>{t("Quay lại", "Go back")}</button>
                <button
                  type="button"
                  className="is-danger"
                  onClick={() => {
                    const run = confirmAction.run;
                    setConfirmAction(null);
                    run();
                  }}
                >
                  {confirmAction.confirmLabel}
                </button>
              </footer>
            </section>
          </div>
        )}
        {preview && (
          <div
            className="flow-preview-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setPreview(null);
            }}
          >
            <section
              className="flow-preview-dialog"
              role="dialog"
              aria-modal="true"
              aria-label={t("Xem trước kết quả", "Output preview")}
            >
              <header>
                <div>
                  <strong>{t("Xem trước kết quả", "Output preview")}</strong>
                  <small>{preview.job.prompt}</small>
                </div>
                <button
                  type="button"
                  onClick={() => setPreview(null)}
                  aria-label={t("Đóng xem trước", "Close preview")}
                >
                  ×
                </button>
              </header>
              <div className="flow-preview-media">
                {preview.job.kind === "video" ? (
                  <video
                    src={`/api/flow/jobs/${preview.job.id}/outputs/${preview.outputIndex}`}
                    controls
                    autoPlay
                  />
                ) : (
                  <img
                    src={`/api/flow/jobs/${preview.job.id}/outputs/${preview.outputIndex}`}
                    alt={preview.job.prompt}
                  />
                )}
              </div>
              <footer>
                {isDesktopApp ? (
                  <button
                    type="button"
                    onClick={() =>
                      revealOutput(preview.job.id, preview.outputIndex)
                    }
                  >
                    {t("Mở thư mục", "Open folder")}
                  </button>
                ) : (
                  <a
                    href={`/api/flow/jobs/${preview.job.id}/outputs/${preview.outputIndex}?download=1`}
                    download
                  >
                    <IconDownload size={15} />
                    {t("Tải về", "Download")}
                  </a>
                )}
                <button type="button" onClick={() => setPreview(null)}>
                  {t("Đóng", "Close")}
                </button>
              </footer>
            </section>
          </div>
        )}
      </section>
    </main>
  );
}

function FlowSelect({
  label,
  value,
  onChange,
  options,
  suffix = "",
  online = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
  suffix?: string;
  online?: boolean;
}) {
  return (
    <label>
      <span>{label}</span>
      <div className="flow-select-wrap">
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
              {suffix}
            </option>
          ))}
        </select>
        {online && <i>Online</i>}
      </div>
    </label>
  );
}
