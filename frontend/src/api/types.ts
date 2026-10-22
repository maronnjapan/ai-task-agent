// Types mirroring the backend OpenAPI contract (backend/app/schemas/*).
// Keep field names identical to the API; the UI maps them to Japanese labels in lib/format.ts.

export type TaskStatus = 'todo' | 'in_progress' | 'review_pending' | 'blocked' | 'completed';
export type Assignee = 'user' | 'ai' | 'shared';
export type MemoryScope = 'global' | 'category' | 'task';
export type MemoryKind = 'hypothesis' | 'ai_inference' | 'research' | 'decision';

export interface Message {
  ok?: boolean;
  message?: string;
  data?: Record<string, unknown> | null;
}

// ---- Tasks ----------------------------------------------------------------

export interface TaskOut {
  id: string;
  title: string;
  description: string | null;
  due_at: string | null;
  category_id: string | null;
  category_name?: string | null;
  status: string;
  assignee: string;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
  ai_activity?: string | null;
  pending_artifacts?: number;
  active_plan_id?: string | null;
  open_chats?: number;
}

export interface TaskListOut {
  items: TaskOut[];
  total: number;
  limit: number;
  offset: number;
}

export interface TaskListParams {
  status?: string;
  category_id?: string;
  assignee?: string;
  search?: string;
  include_completed?: boolean;
  include_deleted?: boolean;
  order?: 'due' | 'created' | 'updated';
  limit?: number;
  offset?: number;
}

export interface TaskCreate {
  title: string;
  description?: string | null;
  due_at?: string | null;
  category_id?: string | null;
  status?: TaskStatus;
  assignee?: Assignee;
}

export interface TaskUpdate {
  title?: string | null;
  description?: string | null;
  due_at?: string | null;
  category_id?: string | null;
  status?: TaskStatus | null;
  assignee?: Assignee | null;
  change_summary?: string | null;
  clear?: string[];
}

export interface ApproveRequest {
  comment?: string | null;
}

export interface RevisionRequest {
  instructions: string;
  kind?: string;
}

export interface TaskRevert {
  version: number;
}

export interface TaskVersionOut {
  id: string;
  task_id: string;
  version: number;
  title: string;
  description: string | null;
  revised_content: Record<string, unknown>;
  previous_content: Record<string, unknown> | null;
  changed_by: string;
  change_summary: string | null;
  created_at: string;
}

export interface TaskContextOut {
  id: string;
  task_id: string;
  context: string;
  source: string | null;
  status: string;
  created_at: string;
}

export interface TaskContextCreate {
  context: string;
  source?: string | null;
}

export interface CategoryOut {
  id: string;
  name: string;
  created_at: string;
  task_count?: number;
}

// ---- Chats & decisions ----------------------------------------------------

export interface ChatOut {
  id: string;
  task_id: string;
  title: string;
  created_at: string;
  message_count?: number;
  last_message_at?: string | null;
}

export interface MessageOut {
  id: string;
  chat_id: string;
  author_type: string;
  content: string;
  created_at: string;
}

export interface MessagePage {
  items: MessageOut[];
  has_more: boolean;
  next_before?: string | null;
}

export interface MessageCreate {
  content: string;
  author_type?: string;
  reply?: boolean;
}

export interface DecisionOut {
  id: string;
  task_id: string;
  content: string;
  source_message_id: string | null;
  supersedes_id: string | null;
  status: string;
  decided_by: string;
  decided_at: string;
}

export interface DecisionCreate {
  content: string;
  source_message_id?: string | null;
  supersedes_id?: string | null;
}

// ---- Manager / execution --------------------------------------------------

export interface InstructionOut {
  run_id: string;
  status: string;
  response: string;
  changes?: Record<string, unknown>[];
}

export interface ManagerStatusOut {
  state: string;
  activity?: string | null;
  current_run_id?: string | null;
  last_run_at?: string | null;
  last_result?: string | null;
  next_scheduled_at?: string | null;
  pending_review_count?: number;
  active_plan_count?: number;
  queued_events?: number;
  llm_ready?: boolean;
  llm_issue?: string | null;
  consecutive_no_progress?: number;
}

export interface AgentRunOut {
  id: string;
  execution_plan_id: string | null;
  work_item_id: string | null;
  agent_type: string;
  status: string;
  model: string | null;
  trigger: string | null;
  input_summary: string | null;
  result_summary: string | null;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
}

export interface ScheduledActionOut {
  id: string;
  task_id: string | null;
  execution_plan_id: string | null;
  action_type: string;
  payload: Record<string, unknown> | null;
  scheduled_at: string;
  status: string;
  created_at: string;
  executed_at: string | null;
}

export interface PlanTaskLinkOut {
  task_id: string;
  execution_plan_id: string;
  acceptance_criteria: string | null;
  task_title?: string | null;
}

export interface ExecutionPlanOut {
  id: string;
  parent_plan_id: string | null;
  objective: string;
  acceptance_criteria: string;
  status: string;
  replanning_attempt: number;
  created_at: string;
  updated_at: string;
  task_links?: PlanTaskLinkOut[];
  work_item_count?: number;
}

export interface WorkItemOut {
  id: string;
  execution_plan_id: string;
  title: string;
  description: string;
  status: string;
  result: Record<string, unknown> | null;
  order_index: number;
  retry_count: number;
  depends_on?: string[];
  created_at: string;
  updated_at: string;
}

export interface ReviewTaskResultOut {
  task_id: string;
  status: string;
  feedback: string | null;
}

export interface ReviewOut {
  id: string;
  execution_plan_id: string;
  agent_run_id: string;
  status: string;
  feedback: string;
  created_at: string;
  task_results?: ReviewTaskResultOut[];
}

// ---- Artifacts ------------------------------------------------------------

export interface ArtifactSourceOut {
  id: string;
  title: string;
  reference: string;
  source_type: string;
  note: string | null;
  created_at: string;
}

export interface ArtifactOut {
  id: string;
  task_id: string | null;
  work_item_id: string | null;
  execution_plan_id: string | null;
  title: string;
  file_path: string;
  absolute_path?: string | null;
  artifact_type: string;
  version: number;
  status: string;
  created_at: string;
  updated_at: string;
  linked_task_ids?: string[];
  sources?: ArtifactSourceOut[];
}

export interface ArtifactContentOut {
  id: string;
  version: number;
  content: string;
}

export interface ArtifactVersionOut {
  id: string;
  artifact_id: string;
  version: number;
  file_path: string;
  created_by: string;
  change_note: string | null;
  created_at: string;
}

export type DiffLineType = 'context' | 'added' | 'removed';

export interface DiffLine {
  type: DiffLineType;
  text: string;
}

export interface ArtifactDiffOut {
  from_version: number;
  to_version: number;
  unified: string;
  lines: DiffLine[];
}

// ---- Memories & user state ------------------------------------------------

export interface MemoryOut {
  id: string;
  scope: string;
  category_id: string | null;
  task_id: string | null;
  content: string;
  source: string | null;
  kind: string;
  confirmed: boolean;
  created_at: string;
  updated_at: string;
}

export interface MemoryCreate {
  scope?: MemoryScope;
  category_id?: string | null;
  task_id?: string | null;
  content: string;
  source?: string | null;
  kind?: MemoryKind;
  confirmed?: boolean;
}

export interface MemoryUpdate {
  content?: string | null;
  source?: string | null;
  kind?: MemoryKind | null;
  confirmed?: boolean | null;
}

export interface UserStateOut {
  condition: string;
  source: string;
  expires_at: string | null;
  updated_at: string;
  active?: boolean;
}

export interface UserStateUpdate {
  condition: string;
  expires_in_minutes?: number | null;
  source?: string;
}

// ---- Notifications / approvals / audit ------------------------------------

export interface NotificationOut {
  id: string;
  title: string;
  body: string;
  level: string;
  status: string;
  channel: string;
  task_id: string | null;
  source: string;
  created_at: string;
  read_at: string | null;
}

export interface NotificationListOut {
  items: NotificationOut[];
  total: number;
  unread: number;
}

export interface ApprovalOut {
  id: string;
  kind: string;
  connection_id: string | null;
  tool_name: string;
  arguments: Record<string, unknown>;
  task_id: string | null;
  work_item_id: string | null;
  reason: string | null;
  status: string;
  result: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface ApprovalDecision {
  approve: boolean;
  comment?: string | null;
}

export interface AuditEventOut {
  id: string;
  event_type: string;
  entity_type: string | null;
  entity_id: string | null;
  actor: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditListOut {
  items: AuditEventOut[];
  total: number;
}

// ---- Integrations (MCP) ---------------------------------------------------

export type ToolPermission = 'read' | 'internal_write' | 'external_write';

export interface ToolPermissionIn {
  tool_name: string;
  permission?: string;
  enabled?: boolean;
}

export interface ToolPermissionOut {
  tool_name: string;
  permission: string;
  enabled: boolean;
}

export interface ToolOut {
  name: string;
  description?: string | null;
  input_schema?: Record<string, unknown>;
  permission?: string;
  enabled?: boolean;
}

export interface IntegrationOut {
  id: string;
  name: string;
  adapter: string;
  transport: string;
  command: string | null;
  args: string[];
  env: Record<string, string>;
  url: string | null;
  headers: Record<string, string>;
  auth_type: string;
  auth_config: Record<string, unknown>;
  has_secret: boolean;
  secret_ref: string | null;
  timeout_seconds: number;
  enabled: boolean;
  allowed_tools: string[];
  tool_permissions: ToolPermissionOut[];
  last_error: string | null;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
  oauth_authorized?: boolean;
}

export interface IntegrationCreate {
  name: string;
  adapter?: string;
  transport?: string;
  command?: string | null;
  args?: string[];
  env?: Record<string, string>;
  url?: string | null;
  headers?: Record<string, string>;
  auth_type?: string;
  auth_config?: Record<string, unknown>;
  secret?: string | null;
  timeout_seconds?: number;
  enabled?: boolean;
  allowed_tools?: string[];
  tool_permissions?: ToolPermissionIn[];
}

export interface IntegrationUpdate {
  name?: string | null;
  adapter?: string | null;
  transport?: string | null;
  command?: string | null;
  args?: string[] | null;
  env?: Record<string, string> | null;
  url?: string | null;
  headers?: Record<string, string> | null;
  auth_type?: string | null;
  auth_config?: Record<string, unknown> | null;
  secret?: string | null;
  timeout_seconds?: number | null;
  enabled?: boolean | null;
  allowed_tools?: string[] | null;
  tool_permissions?: ToolPermissionIn[] | null;
}

export interface AdapterPresetOut {
  adapter: string;
  label: string;
  description: string;
  transport: string;
  command?: string | null;
  args?: string[];
  url?: string | null;
  auth_type?: string;
  auth_config?: Record<string, unknown>;
  env_hints?: Record<string, string>;
  tool_permissions?: ToolPermissionIn[];
}

export interface ConnectionTestOut {
  ok: boolean;
  message: string;
  tools?: ToolOut[];
  server_name?: string | null;
  duration_ms?: number;
}

export interface OAuthStartOut {
  authorization_url?: string;
  state?: string;
  [key: string]: unknown;
}

// ---- Settings -------------------------------------------------------------

export interface LLMAgentSettings {
  provider?: string;
  model?: string;
  temperature?: number;
  timeout_seconds?: number;
  max_retries?: number;
  custom_prompt?: string;
  extra?: Record<string, unknown>;
}

export interface LLMSettings {
  manager?: LLMAgentSettings;
  worker?: LLMAgentSettings;
  review?: LLMAgentSettings;
}

export interface ManagerSettingsOut {
  custom_prompt?: string;
  autonomy_level?: string;
  reminder_aggressiveness?: string;
  reevaluation_interval_minutes?: number;
  max_replanning_attempts?: number;
  max_worker_retries?: number;
  max_consecutive_no_progress?: number;
}

export interface NotificationSettings {
  level?: string;
  desktop_enabled?: boolean;
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  min_interval_seconds?: number;
  dedupe_window_minutes?: number;
  pending_review_reminder_hours?: number;
}

export interface LocalSourceSettings {
  directories?: string[];
  extensions?: string[];
  max_file_size_kb?: number;
}

export interface BackupSettings {
  directory?: string | null;
  auto_backup_interval_hours?: number;
  keep_last?: number;
}

export interface ProviderKeyStatus {
  provider: string;
  secret_name: string;
  configured: boolean;
  backend: string;
}

export interface SettingsOut {
  llm: LLMSettings;
  manager: ManagerSettingsOut;
  notifications: NotificationSettings;
  local_sources: LocalSourceSettings;
  backup: BackupSettings;
  platform: Record<string, unknown>;
  secret_backend: string;
  api_keys: ProviderKeyStatus[];
  autostart_installed: boolean;
  data_directory: string;
  env_file: string;
  app: { host?: string; port?: number; auto_start_manager?: boolean; providers?: string[]; [key: string]: unknown };
}

export interface SettingsPatch {
  llm?: LLMSettings | null;
  manager?: ManagerSettingsOut | null;
  notifications?: NotificationSettings | null;
  local_sources?: LocalSourceSettings | null;
  backup?: BackupSettings | null;
}

// ---- System ---------------------------------------------------------------

export interface SystemStatusOut {
  version: string;
  platform: Record<string, unknown>;
  data_directory: string;
  database_path: string;
  uptime_seconds: number;
  manager: Record<string, unknown>;
  counts: Record<string, number>;
  sse_subscribers: number;
  autostart_installed: boolean;
  pid: number;
  secret_backend: string;
}

export interface BackupOut {
  path: string;
  size_bytes: number;
  created_at: string;
  includes?: string[];
}

export interface RestoreOut {
  restored_from: string;
  safety_backup: string;
  message: string;
}

// ---- Server-Sent Events ---------------------------------------------------

export type SseEventType =
  | 'hello'
  | 'ping'
  | 'task.created'
  | 'task.updated'
  | 'task.deleted'
  | 'chat.created'
  | 'chat.message'
  | 'chat.typing'
  | 'decision.recorded'
  | 'artifact.created'
  | 'artifact.updated'
  | 'plan.created'
  | 'plan.updated'
  | 'work_items.created'
  | 'work_item.updated'
  | 'agent_run.started'
  | 'agent_run.finished'
  | 'review.recorded'
  | 'notification.created'
  | 'notification.read'
  | 'approval.requested'
  | 'approval.resolved'
  | 'manager.status'
  | 'settings.updated'
  | 'integration.oauth'
  | 'system.restored';

export interface SseEvent<T = Record<string, unknown>> {
  id: number | string;
  type: SseEventType | string;
  data: T;
  created_at: string;
}
