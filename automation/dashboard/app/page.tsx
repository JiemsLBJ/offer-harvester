'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  FluentProvider,
  Input,
  Select,
  Textarea,
  webDarkTheme,
} from '@fluentui/react-components';
import {
  AppsListDetail24Regular,
  ArrowSync24Regular,
  Briefcase24Regular,
  DataTrending24Regular,
  DatabaseSearch24Regular,
  Pulse24Regular,
  Settings24Regular,
} from '@fluentui/react-icons';

type Tab = 'overview' | 'pipeline' | 'learning' | 'sources';
type Scope = 'gaps' | 'done' | 'all';

type Application = {
  id: string;
  portal: string;
  company: string;
  title: string;
  url: string;
  status: string;
  sector: string;
  role_type: string;
  location: string;
  work_mode: string;
  fit_rating: string;
  deadline: string;
  contact_person: string;
  next_action: string;
  next_action_date: string;
  notes: string;
  tags: string[];
  resume: string;
  receipt: string;
  error: string;
  updated_at: string;
};

type Requirement = {
  id: string;
  portal: string;
  field_key: string;
  label: string;
  data_type: string;
  required: boolean;
  sensitive: boolean;
  profile_path: string;
  resolution_status: string;
  occurrences: number;
  last_seen: string;
  last_issue: string;
  sample_context: Array<{ company?: string; title?: string; url?: string }>;
};

type SourceRun = {
  id: string;
  portal: string;
  status: string;
  mode: string;
  keyword: string;
  location: string;
  discovered_count: number;
  new_count: number;
  entry_url: string;
  message: string;
  finished_at: string;
  details?: {
    batch_id?: string;
    jobs?: ScrapeJob[];
    errors?: string[];
    raw_count?: number;
  };
};

type ScrapeJob = {
  id?: string;
  title: string;
  company: string;
  location?: string;
  date?: string | null;
  url: string;
  fit?: string;
  is_new?: boolean;
  already_tracked?: boolean;
};

type ScrapeActivity = {
  date: string;
  discovered_count: number;
  new_count: number;
  runs: number;
};

type JobSource = {
  portal: string;
  name: string;
  category: 'platform' | 'company' | 'history';
  tier: string;
  enabled: boolean;
  mode: string;
  entry_url: string;
  cadence: string;
  description: string;
  seen_count: number;
  health: string;
  message: string;
  evidence_at?: string;
  last_run?: SourceRun | null;
};

type Payload = {
  applications: Application[];
  requirements: Requirement[];
  sources: JobSource[];
  source_runs: SourceRun[];
  scrape_activity: ScrapeActivity[];
  source_summary: {
    primary: number;
    enabled: number;
    healthy: number;
    warnings: number;
    tracked_jobs: number;
    batches: number;
  };
  summary: {
    total: number;
    active: number;
    applied: number;
    interview: number;
    offer: number;
    missing_fields: number;
    status_counts: Record<string, number>;
    portal_counts: Record<string, number>;
    activity: Array<{ date: string; count: number }>;
  };
};

const API = 'http://127.0.0.1:8765/api';
const STATUS_LABELS: Record<string, string> = {
  discovered: '已发现', drafted: '准备材料', blocked: '等待处理', filled: '已填表',
  cancelled: '暂未提交', applied: '已投递', interview: '面试中', offer: '已获 Offer',
  hired: '已入职', rejected: '未通过', no_response: '暂无回复',
  offer_declined: '已婉拒 Offer', withdrawn: '已撤回',
};
const STATUS_OPTIONS = Object.entries(STATUS_LABELS);
const PORTAL_LABELS: Record<string, string> = {
  bytedance: '字节招聘', tencent: '腾讯招聘', shixiseng: '实习僧', xiaohongshu: '小红书',
  bilibili: '哔哩哔哩', zhaopin: '智联招聘', boss: 'BOSS直聘', nowcoder: '牛客',
  linkedin: 'LinkedIn Jobs', freehire: 'FreeHire', generic: '通用填表', portal: '手工记录',
};
const GAP_STATUSES = new Set(['missing', 'unmapped']);
const EMPTY_APPLICATIONS: Application[] = [];
const EMPTY_REQUIREMENTS: Requirement[] = [];

const pipelineColumns = [
  { key: 'preparing', title: '准备中', statuses: ['discovered', 'drafted', 'blocked', 'filled', 'cancelled'] },
  { key: 'applied', title: '已投递', statuses: ['applied'] },
  { key: 'interview', title: '面试', statuses: ['interview'] },
  { key: 'result', title: '结果', statuses: ['offer', 'hired', 'rejected', 'no_response', 'offer_declined', 'withdrawn'] },
];

function portalLabel(value: string) {
  return PORTAL_LABELS[value] || value || '其他渠道';
}

function statusLabel(value: string) {
  return STATUS_LABELS[value] || value;
}

function shortDate(value: string) {
  return value ? value.slice(0, 10) : '未设置';
}

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const data = await response.json() as T & { error?: string };
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data as T;
}

export default function Home() {
  const [tab, setTab] = useState<Tab>('overview');
  const [payload, setPayload] = useState<Payload | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Application | null>(null);
  const [scope, setScope] = useState<Scope>('gaps');
  const [selectedRequirement, setSelectedRequirement] = useState<Requirement | null>(null);
  const [profilePath, setProfilePath] = useState('');
  const [answer, setAnswer] = useState('');

  const load = useCallback(async () => {
    try {
      setError('');
      setPayload(await requestJson<Payload>(`${API}/dashboard`));
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法连接本机数据服务');
    }
  }, []);

  useEffect(() => {
    let active = true;
    requestJson<Payload>(`${API}/dashboard`).then((data) => {
      if (active) setPayload(data);
    }).catch((err: unknown) => {
      if (active) setError(err instanceof Error ? err.message : '无法连接本机数据服务');
    });
    return () => { active = false; };
  }, []);

  const sync = async () => {
    setBusy(true);
    try {
      const result = await requestJson<{ data: Payload }>(`${API}/sync`, { method: 'POST' });
      setPayload(result.data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '同步失败');
    } finally {
      setBusy(false);
    }
  };

  const patchApplication = async (id: string, changes: Record<string, unknown>) => {
    setBusy(true);
    try {
      const result = await requestJson<{ application: Application }>(`${API}/applications/${id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
      });
      setSelected(result.application);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '岗位更新失败');
    } finally {
      setBusy(false);
    }
  };

  const openRequirement = (item: Requirement) => {
    setSelectedRequirement(item);
    setProfilePath(item.profile_path || `form_answers.${item.field_key}`);
    setAnswer('');
  };

  const resolveRequirement = async (action: 'save' | 'manual' | 'ignored' | 'missing') => {
    if (!selectedRequirement) return;
    setBusy(true);
    try {
      let value: string | number = answer;
      if (selectedRequirement.data_type === 'number' && answer !== '') value = Number(answer);
      await requestJson<{ ok: boolean }>(`${API}/requirements/${selectedRequirement.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, profile_path: profilePath, value }),
      });
      setSelectedRequirement(null);
      setAnswer('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '资料处理失败');
    } finally {
      setBusy(false);
    }
  };

  const applications = payload?.applications || EMPTY_APPLICATIONS;
  const requirements = payload?.requirements || EMPTY_REQUIREMENTS;
  const summary = payload?.summary;
  const filteredApplications = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? applications.filter((app) => `${app.company} ${app.title} ${app.portal} ${app.tags.join(' ')}`.toLowerCase().includes(needle)) : applications;
  }, [applications, query]);
  const visibleRequirements = useMemo(() => requirements.filter((item) => {
    if (scope === 'gaps') return GAP_STATUSES.has(item.resolution_status) || item.resolution_status === 'manual_sensitive';
    if (scope === 'done') return ['covered', 'manual', 'ignored'].includes(item.resolution_status);
    return true;
  }), [requirements, scope]);
  const maxActivity = Math.max(1, ...(summary?.activity || []).map((item) => item.count));

  return (
    <FluentProvider theme={webDarkTheme} className="app-provider">
      <main className="app-shell">
        <aside className="sidebar">
          <div className="brand-mark" aria-label="求职进度中心">P</div>
          <nav aria-label="主导航">
            <button title="总览" className={`nav-item ${tab === 'overview' ? 'active' : ''}`} onClick={() => setTab('overview')}><DataTrending24Regular /></button>
            <button title="投递管线" className={`nav-item ${tab === 'pipeline' ? 'active' : ''}`} onClick={() => setTab('pipeline')}><Briefcase24Regular /></button>
            <button title="资料缺口" className={`nav-item ${tab === 'learning' ? 'active' : ''}`} onClick={() => setTab('learning')}><DatabaseSearch24Regular /></button>
            <button title="来源监控" className={`nav-item ${tab === 'sources' ? 'active' : ''}`} onClick={() => setTab('sources')}><Pulse24Regular /></button>
          </nav>
          <button title="设置" className="nav-item settings"><Settings24Regular /></button>
        </aside>

        <section className="workspace">
          <header className="topbar">
            <div>
              <p className="context-label">{tab === 'overview' ? '求职进度中心' : tab === 'pipeline' ? '投递管线' : tab === 'learning' ? '表单学习库' : '岗位来源监控'}</p>
              <h1>{tab === 'overview' ? '把每一次投递变成可推进的进度' : tab === 'pipeline' ? '每个岗位都知道下一步做什么' : tab === 'learning' ? '遇到一次新字段，以后就能自动处理' : '清楚知道每个岗位从哪里来'}</h1>
            </div>
            <Button
              appearance="primary"
              className="sync-button"
              icon={<ArrowSync24Regular />}
              aria-label={busy ? '正在同步记录' : '同步记录'}
              title={busy ? '正在同步记录' : '同步记录'}
              disabled={busy}
              onClick={() => void sync()}
            >
              <span className="sync-label">{busy ? '处理中' : '同步记录'}</span>
            </Button>
          </header>

          {error && <div className="error-banner" role="alert"><strong>暂时无法完成操作</strong><span>{error}</span><button onClick={() => void load()}>重试</button></div>}
          {!payload && !error && <LoadingState />}
          {payload && tab === 'overview' && (
            <Overview summary={summary!} applications={applications} requirements={requirements} maxActivity={maxActivity} onPipeline={() => setTab('pipeline')} onLearning={() => setTab('learning')} onSelect={setSelected} />
          )}
          {payload && tab === 'pipeline' && (
            <Pipeline applications={filteredApplications} query={query} onQuery={setQuery} onSelect={setSelected} onStatus={(app, status) => void patchApplication(app.id, { status })} />
          )}
          {payload && tab === 'learning' && (
            <Learning requirements={visibleRequirements} all={requirements} scope={scope} onScope={setScope} onSelect={openRequirement} />
          )}
          {payload && tab === 'sources' && (
            <Sources sources={payload.sources || []} runs={payload.source_runs || []} activity={payload.scrape_activity || []} summary={payload.source_summary} />
          )}
        </section>
      </main>

      {selected && <ApplicationDrawer application={selected} busy={busy} onClose={() => setSelected(null)} onChange={setSelected} onSave={() => void patchApplication(selected.id, selected)} />}
      {selectedRequirement && <RequirementDrawer item={selectedRequirement} profilePath={profilePath} answer={answer} busy={busy} onPath={setProfilePath} onAnswer={setAnswer} onClose={() => setSelectedRequirement(null)} onAction={(action) => void resolveRequirement(action)} />}
    </FluentProvider>
  );
}

function LoadingState() {
  return <div className="loading-grid" aria-label="正在读取求职记录">{[1, 2, 3, 4, 5, 6].map((item) => <span key={item} />)}</div>;
}

function Overview({ summary, applications, requirements, maxActivity, onPipeline, onLearning, onSelect }: {
  summary: Payload['summary']; applications: Application[]; requirements: Requirement[]; maxActivity: number;
  onPipeline: () => void; onLearning: () => void; onSelect: (app: Application) => void;
}) {
  const funnel = [
    ['准备中', ['discovered', 'drafted', 'blocked', 'filled', 'cancelled'].reduce((n, key) => n + (summary.status_counts[key] || 0), 0)],
    ['已投递', summary.applied], ['面试', summary.interview], ['Offer', summary.offer],
  ] as Array<[string, number]>;
  const gaps = requirements.filter((item) => GAP_STATUSES.has(item.resolution_status) || item.resolution_status === 'manual_sensitive');
  return <>
    <section className="metric-strip" aria-label="投递概况">
      <Metric label="全部岗位" value={summary.total} note="机器人和手工记录" />
      <Metric label="推进中" value={summary.active} note="等待操作的岗位" />
      <Metric label="面试" value={summary.interview} note="进入面试流程" />
      <Metric label="Offer" value={summary.offer} note="等待决定或已接受" />
    </section>

    <div className="overview-grid">
      <section className="panel activity-panel">
        <div className="panel-heading"><div><h2>推进节奏</h2><p>最近的状态变化与投递漏斗</p></div></div>
        <div className="activity-chart" aria-label="最近活动">
          {(summary.activity.length ? summary.activity : [{ date: '暂无', count: 0 }]).map((item) => <div className="activity-day" key={item.date}><span style={{ height: `${Math.max(8, item.count / maxActivity * 100)}%` }} /><small>{item.date.slice(5) || item.date}</small></div>)}
        </div>
        <div className="funnel-row">{funnel.map(([label, count]) => <div key={label}><strong>{count}</strong><span>{label}</span></div>)}</div>
      </section>

      <aside className="panel portal-panel">
        <div className="panel-heading"><div><h2>渠道分布</h2><p>岗位来自哪些招聘入口</p></div></div>
        <div className="portal-list">{Object.entries(summary.portal_counts).sort((a, b) => b[1] - a[1]).map(([portal, count]) => <div key={portal}><span>{portalLabel(portal)}</span><strong>{count}</strong></div>)}</div>
      </aside>
    </div>

    <div className="content-grid">
      <section className="panel pipeline-panel">
        <div className="panel-heading"><div><h2>当前投递</h2><p>最近更新的岗位排在前面</p></div><button className="text-action" onClick={onPipeline}>查看管线</button></div>
        <div className="job-list">{applications.slice(0, 5).map((app) => <JobRow key={app.id} app={app} onClick={() => onSelect(app)} />)}{!applications.length && <EmptyState text="还没有岗位记录，完成一次填表或同步 tracker 后会自动出现。" />}</div>
      </section>
      <aside className="panel learning-panel">
        <DatabaseSearch24Regular className="learning-icon" />
        <p>表单学习</p><strong>{gaps.length} 项资料待处理</strong>
        <span>{gaps[0] ? `${portalLabel(gaps[0].portal)}出现了“${gaps[0].label}”。补充后可在未来同类表单中复用。` : '目前没有未处理的资料缺口。新的表单字段会自动出现在这里。'}</span>
        <Button appearance="secondary" icon={<AppsListDetail24Regular />} onClick={onLearning}>打开资料缺口</Button>
      </aside>
    </div>
  </>;
}

function Metric({ label, value, note }: { label: string; value: number; note: string }) {
  return <div><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

function JobRow({ app, onClick }: { app: Application; onClick: () => void }) {
  return <button className="job-row" onClick={onClick}>
    <span className="company-avatar">{app.company.slice(0, 1)}</span>
    <span className="job-copy"><strong>{app.company}</strong><span>{app.title}</span></span>
    <span className="portal-name">{portalLabel(app.portal)}</span>
    <span className={`status-label status-${app.status}`}>{statusLabel(app.status)}</span>
  </button>;
}

function Pipeline({ applications, query, onQuery, onSelect, onStatus }: {
  applications: Application[]; query: string; onQuery: (value: string) => void;
  onSelect: (app: Application) => void; onStatus: (app: Application, status: string) => void;
}) {
  return <section className="pipeline-view">
    <div className="toolbar"><Input value={query} onChange={(_, data) => onQuery(data.value)} placeholder="搜索公司、岗位、渠道或标签" aria-label="搜索岗位" /><span>{applications.length} 个岗位</span></div>
    <div className="kanban">
      {pipelineColumns.map((column) => {
        const jobs = applications.filter((app) => column.statuses.includes(app.status));
        return <section className="kanban-column" key={column.key}>
          <header><h2>{column.title}</h2><span>{jobs.length}</span></header>
          <div className="kanban-list">{jobs.map((app) => <article className="job-card" key={app.id}>
            <button className="job-card-main" onClick={() => onSelect(app)}><span>{portalLabel(app.portal)}</span><strong>{app.company}</strong><p>{app.title}</p>{app.tags.length > 0 && <div className="tag-row">{app.tags.slice(0, 3).map((tag) => <em key={tag}>{tag}</em>)}</div>}</button>
            <Select value={app.status} aria-label={`更新${app.company}的状态`} onChange={(event) => onStatus(app, event.target.value)}>{STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select>
            <footer><span>{app.next_action || '尚未设置下一步'}</span><small>{app.next_action_date ? shortDate(app.next_action_date) : shortDate(app.updated_at)}</small></footer>
          </article>)}{!jobs.length && <EmptyState text="这个阶段暂时没有岗位。" />}</div>
        </section>;
      })}
    </div>
  </section>;
}

function Learning({ requirements, all, scope, onScope, onSelect }: {
  requirements: Requirement[]; all: Requirement[]; scope: Scope; onScope: (scope: Scope) => void; onSelect: (item: Requirement) => void;
}) {
  const gapCount = all.filter((item) => GAP_STATUSES.has(item.resolution_status)).length;
  const coveredCount = all.filter((item) => item.resolution_status === 'covered').length;
  return <section className="learning-view">
    <div className="learning-summary">
      <div><span>待补资料</span><strong>{gapCount}</strong></div><div><span>已覆盖字段</span><strong>{coveredCount}</strong></div><div><span>累计学习</span><strong>{all.length}</strong></div>
    </div>
    <div className="scope-tabs" role="tablist"><button className={scope === 'gaps' ? 'active' : ''} onClick={() => onScope('gaps')}>待处理</button><button className={scope === 'done' ? 'active' : ''} onClick={() => onScope('done')}>已处理</button><button className={scope === 'all' ? 'active' : ''} onClick={() => onScope('all')}>全部字段</button></div>
    <div className="requirements-grid">{requirements.map((item) => <button className="requirement-card" key={item.id} onClick={() => onSelect(item)}>
      <div><span>{portalLabel(item.portal)}</span><em>{item.required ? '必填' : '选填或待确认'}</em></div><strong>{item.label}</strong>
      <p>{item.last_issue || (item.profile_path ? `档案路径：${item.profile_path}` : '尚未映射到结构化档案')}</p>
      <footer><span className={`requirement-state state-${item.resolution_status}`}>{requirementLabel(item.resolution_status)}</span><small>{item.occurrences || 1} 个岗位出现</small></footer>
    </button>)}{!requirements.length && <EmptyState text={scope === 'gaps' ? '当前没有未处理的资料缺口。' : '还没有符合条件的字段记录。'} />}</div>
  </section>;
}

function requirementLabel(value: string) {
  return ({ missing: '待补资料', unmapped: '待建立映射', manual_sensitive: '每次人工填写', covered: '已补齐', manual: '仅人工填写', ignored: '已忽略', observed: '已观察' } as Record<string, string>)[value] || value;
}

function sourceHealthLabel(value: string) {
  return ({ success: '正常', historical: '有历史数据', warning: '需要检查', error: '抓取失败', not_run: '尚未运行', inactive: '未接入' } as Record<string, string>)[value] || value;
}

function sourceTierLabel(value: string) {
  return ({ primary: '主来源', supplemental: '补充来源', assist: '人工辅助', inactive: '尚未接入', history: '历史来源' } as Record<string, string>)[value] || value;
}

function Sources({ sources, runs, activity, summary }: { sources: JobSource[]; runs: SourceRun[]; activity: ScrapeActivity[]; summary: Payload['source_summary'] }) {
  const metrics = summary || { primary: 0, enabled: 0, healthy: 0, warnings: 0, tracked_jobs: 0, batches: 0 };
  const dailyNames = sources.filter((source) => source.enabled && source.cadence === '日常同步').map((source) => source.name);
  const maxScraped = Math.max(1, ...activity.map((item) => item.discovered_count));
  const sourceGroups = [
    { key: 'platform', title: '通用招聘平台', note: '聚合平台与综合招聘网站' },
    { key: 'company', title: '重点公司招聘官网', note: '优先跟进的数据、AI、量化与研究岗位官网' },
    { key: 'history', title: '历史补充来源', note: '保留用于去重和岗位评估，不等同于持续抓取' },
  ];
  return <section className="sources-view">
    <div className="source-summary" aria-label="岗位来源概况">
      <Metric label="主来源" value={metrics.primary} note="日常自动同步" />
      <Metric label="已启用来源" value={metrics.enabled} note="包含按需浏览器来源" />
      <Metric label="已有岗位" value={metrics.tracked_jobs} note="当前岗位库来源总量" />
      <Metric label="抓取批次" value={metrics.batches} note={`${metrics.warnings} 个来源需检查`} />
    </div>
    <div className="source-guidance panel">
      <div><span>当前日常自动同步</span><strong>{dailyNames.join(' + ') || '暂无'}</strong></div>
      <p>其余来源也已进入地图，但只有标为“正常 / 有历史数据 / 尚未运行”的启用来源才代表已有抓取能力；“未接入”只表示已规划，不会伪装成成功结果。</p>
    </div>
    <section className="panel scrape-timeline">
      <div className="panel-heading">
        <div><h2>抓取时间序列</h2><p>按日期汇总读取岗位与本次新增，柱高使用同一尺度</p></div>
        <div className="chart-legend"><span className="legend-discovered">读取</span><span className="legend-new">新增</span></div>
      </div>
      <div className="scrape-chart" aria-label="抓取岗位时间序列柱状图">
        {(activity.length ? activity : [{ date: '暂无', discovered_count: 0, new_count: 0, runs: 0 }]).map((item) => (
          <div className="scrape-day" key={item.date} title={`${item.date}：读取 ${item.discovered_count}，新增 ${item.new_count}`}>
            <div className="scrape-bars">
              <span className="bar-discovered" style={{ height: item.discovered_count ? `${Math.max(5, item.discovered_count / maxScraped * 100)}%` : '0%' }} />
              <span className="bar-new" style={{ height: item.new_count ? `${Math.max(5, item.new_count / maxScraped * 100)}%` : '0%' }} />
            </div>
            <strong>{item.new_count}</strong>
            <small>{item.date.slice(5) || item.date}</small>
          </div>
        ))}
      </div>
    </section>
    {sourceGroups.map((group) => {
      const items = sources.filter((source) => (source.category || 'history') === group.key);
      if (!items.length) return null;
      return <section className="source-group" key={group.key}>
        <div className="panel-heading"><div><h2>{group.title}</h2><p>{group.note}</p></div><span>{items.length} 个来源</span></div>
        <div className="source-grid">
          {items.map((source) => <article className={`source-card health-${source.health}`} key={source.portal}>
        <header>
          <span className="source-avatar">{source.name.slice(0, 1)}</span>
          <div><strong>{source.name}</strong><small>{source.mode}</small></div>
          <span className={`source-health health-${source.health}`}>{sourceHealthLabel(source.health)}</span>
        </header>
        <div className="source-badges"><span>{sourceTierLabel(source.tier)}</span><span>{source.cadence}</span></div>
        <p>{source.description}</p>
        <dl>
          <div><dt>已入库</dt><dd>{source.seen_count} 个岗位</dd></div>
          <div><dt>最近运行</dt><dd>{source.last_run?.finished_at ? shortDate(source.last_run.finished_at) : source.evidence_at ? shortDate(source.evidence_at) : '暂无记录'}</dd></div>
          {source.last_run && <div><dt>最近结果</dt><dd>{source.last_run.discovered_count} 条，新增 {source.last_run.new_count}</dd></div>}
        </dl>
        <div className="source-message">{source.message}</div>
        {source.entry_url && <a href={source.entry_url} target="_blank" rel="noreferrer">查看来源入口</a>}
          </article>)}
        </div>
      </section>;
    })}
    <section className="panel run-history">
      <div className="panel-heading"><div><h2>最近抓取运行与岗位 URL</h2><p>展开任意批次可核验这次实际返回的每一个岗位链接</p></div></div>
      <div className="run-list">
        {runs.slice(0, 12).map((run) => {
          const jobs = run.details?.jobs || [];
          return <details className="run-batch" key={run.id}>
            <summary className="run-row">
              <span className={`run-dot health-${run.status}`} />
              <div><strong>{portalLabel(run.portal)}</strong><small>{run.keyword || '未指定关键词'} · {run.location || '全部地点'}</small></div>
              <span>{run.discovered_count} 条</span><span>新增 {run.new_count}</span><time>{run.finished_at.slice(0, 16)}</time>
            </summary>
            <div className="run-jobs">
              {jobs.map((job) => <a href={job.url} target="_blank" rel="noreferrer" key={`${run.id}-${job.url}`}>
                <span><strong>{job.company || '未知公司'}</strong><small>{job.title}</small></span>
                <span>{job.location || portalLabel(run.portal)}</span>
                <em>{job.is_new ? '本次新增' : job.already_tracked ? '已在投递库' : '已见岗位'}</em>
              </a>)}
              {!jobs.length && <a href={run.entry_url} target="_blank" rel="noreferrer"><span><strong>旧版运行记录</strong><small>该批次记录于 URL 明细功能启用前</small></span><span>来源入口</span><em>查看</em></a>}
            </div>
          </details>;
        })}
        {!runs.length && <EmptyState text="还没有新的抓取运行记录。下一次执行岗位同步后，这里会显示真实结果。" />}
      </div>
    </section>
  </section>;
}

function ApplicationDrawer({ application, busy, onClose, onChange, onSave }: {
  application: Application; busy: boolean; onClose: () => void; onChange: (app: Application) => void; onSave: () => void;
}) {
  const set = (key: keyof Application, value: string | string[]) => onChange({ ...application, [key]: value });
  return <div className="drawer-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="drawer" role="dialog" aria-modal="true" aria-label="岗位详情">
      <header><div><span>{portalLabel(application.portal)}</span><h2>{application.company}</h2><p>{application.title}</p></div><button className="close-button" onClick={onClose} aria-label="关闭">×</button></header>
      <div className="drawer-form">
        <label>当前状态<Select value={application.status} onChange={(event) => set('status', event.target.value)}>{STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select></label>
        <div className="field-pair"><label>行业<Input value={application.sector} onChange={(_, data) => set('sector', data.value)} /></label><label>岗位类型<Input value={application.role_type} onChange={(_, data) => set('role_type', data.value)} /></label></div>
        <div className="field-pair"><label>地点<Input value={application.location} onChange={(_, data) => set('location', data.value)} /></label><label>截止日期<Input type="date" value={application.deadline} onChange={(_, data) => set('deadline', data.value)} /></label></div>
        <label>岗位标签<Input value={application.tags.join(', ')} placeholder="例如：高优先级, 数据分析, 上海" onChange={(_, data) => set('tags', data.value.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean))} /></label>
        <label>下一步<Input value={application.next_action} placeholder="例如：周三准备一面" onChange={(_, data) => set('next_action', data.value)} /></label>
        <label>下一步日期<Input type="date" value={application.next_action_date} onChange={(_, data) => set('next_action_date', data.value)} /></label>
        <label>联系人<Input value={application.contact_person} onChange={(_, data) => set('contact_person', data.value)} /></label>
        <label>备注<Textarea resize="vertical" value={application.notes} onChange={(_, data) => set('notes', data.value)} /></label>
      </div>
      <footer><Button appearance="secondary" onClick={() => window.open(application.url, '_blank', 'noopener,noreferrer')} disabled={!application.url}>打开岗位</Button><Button appearance="primary" onClick={onSave} disabled={busy}>{busy ? '保存中' : '保存修改'}</Button></footer>
    </aside>
  </div>;
}

function RequirementDrawer({ item, profilePath, answer, busy, onPath, onAnswer, onClose, onAction }: {
  item: Requirement; profilePath: string; answer: string; busy: boolean; onPath: (value: string) => void; onAnswer: (value: string) => void; onClose: () => void; onAction: (action: 'save' | 'manual' | 'ignored' | 'missing') => void;
}) {
  const cannotPersist = item.sensitive || item.resolution_status === 'manual_sensitive';
  const context = item.sample_context[0];
  return <div className="drawer-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="drawer requirement-drawer" role="dialog" aria-modal="true" aria-label="补充表单资料">
      <header><div><span>{portalLabel(item.portal)}</span><h2>{item.label}</h2><p>{context?.company ? `${context.company} ${context.title || ''}` : '跨站表单学习记录'}</p></div><button className="close-button" onClick={onClose} aria-label="关闭">×</button></header>
      <div className="requirement-explain"><strong>{requirementLabel(item.resolution_status)}</strong><p>{cannotPersist ? '该字段涉及敏感信息，不会写入任何文件。需要时只在单次投递中人工填写。' : item.last_issue || '补充一次后，后续相同字段会优先从结构化档案读取。'}</p></div>
      {!cannotPersist && <div className="drawer-form"><label>档案路径<Input value={profilePath} onChange={(_, data) => onPath(data.value)} /></label><label>补充内容<Input type={item.data_type === 'date' ? 'date' : item.data_type === 'number' ? 'number' : 'text'} value={answer} onChange={(_, data) => onAnswer(data.value)} /></label><small>内容只保存在本机补充档案中，保存后学习状态会更新为“已补齐”。</small></div>}
      <footer>{item.resolution_status === 'covered' ? <Button appearance="secondary" onClick={() => onAction('missing')} disabled={busy}>重新处理</Button> : <><Button appearance="subtle" onClick={() => onAction('ignored')} disabled={busy}>忽略</Button><Button appearance="secondary" onClick={() => onAction('manual')} disabled={busy}>以后仅手动</Button>{!cannotPersist && <Button appearance="primary" onClick={() => onAction('save')} disabled={busy || !answer.trim() || !profilePath.trim()}>保存并学习</Button>}</>}</footer>
    </aside>
  </div>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state"><AppsListDetail24Regular /><span>{text}</span></div>;
}
