import React, { useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, Bot, Clock3, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import './styles.css';

const FIVE_HOURS = 300;
const ONE_WEEK = 10080;
const providerMeta = {
  codex: { label: 'Codex', mark: 'CX', color: '#65e7bd' },
  claude: { label: 'Claude', mark: 'CL', color: '#ffad83' },
  antigravity: { label: 'Antigravity', mark: 'AG', color: '#a7b8ff' },
};

function formatDuration(minutes) {
  if (minutes === FIVE_HOURS) return '5h';
  if (minutes === ONE_WEEK) return 'Weekly';
  if (minutes % 1440 === 0) return `${minutes / 1440}d`;
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

function formatReset(value) {
  if (!value) return 'Reset unknown';
  const diff = new Date(value).getTime() - Date.now();
  if (diff <= 0) return 'Reset pending';
  const minutes = Math.ceil(diff / 60000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  return `Resets in ${days ? `${days}d ${hours}h` : hours ? `${hours}h ${mins}m` : `${mins}m`}`;
}

function WindowMeter({ title, data, accent }) {
  return <div className={`window ${!data ? 'missing' : ''}`}>
    <div className="window-top"><span>{title}</span>{data && <strong>{data.usedPercent.toFixed(0)}%</strong>}</div>
    {data ? <>
      <div className="meter"><span style={{ width: `${Math.min(100, data.usedPercent)}%`, background: accent }} /></div>
      <small>{formatReset(data.resetsAt)}</small>
    </> : <><div className="meter" /><small>Not reported</small></>}
  </div>;
}

function AccountCard({ account }) {
  const meta = providerMeta[account.provider];
  const fiveHour = account.windows?.find(window => window.windowMinutes === FIVE_HOURS);
  const weekly = account.windows?.find(window => window.windowMinutes === ONE_WEEK);
  const other = account.windows?.find(window => ![FIVE_HOURS, ONE_WEEK].includes(window.windowMinutes));
  const age = account.updatedAt ? Math.max(0, Math.floor((Date.now() - new Date(account.updatedAt)) / 60000)) : null;

  return <article className="account-card" style={{ '--accent': meta.color }}>
    <div className="account-head">
      <div className="agent-mark">{meta.mark}</div>
      <div><span>{meta.label}</span><h2>{account.name}</h2></div>
      <div className={`connection ${account.available ? 'connected' : ''}`}><i />{account.available ? 'Live' : 'Setup'}</div>
    </div>
    {account.available ? <div className="windows">
      <WindowMeter title="Five-hour" data={fiveHour || (other?.windowMinutes < ONE_WEEK ? other : null)} accent={meta.color} />
      <WindowMeter title="Weekly" data={weekly} accent={meta.color} />
    </div> : <div className="account-empty">
      <Bot size={19} /><strong>Usage unavailable</strong><p>{account.message}</p>
      {account.provider === 'codex' && <code>{account.configuredHome}</code>}
    </div>}
    <div className="account-foot">
      <span>{account.planType ? `${account.planType} plan` : account.provider === 'antigravity' ? 'Local log' : 'Local profile'}</span>
      <span>{age == null ? 'Waiting for data' : age === 0 ? 'Updated now' : `Updated ${age}m ago`}</span>
    </div>
  </article>;
}

function App() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/usage', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok || !data.available) throw new Error(data.error || 'Usage endpoint unavailable.');
      setAccounts(data.accounts);
      setError('');
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 60_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const live = accounts.filter(account => account.available).length;
  return <main className="app-shell">
    <header>
      <div className="brand"><span className="brand-mark"><Activity size={17} /></span><span>agent<strong>meter</strong></span></div>
      <div className="live-status"><span /> Local only</div>
    </header>
    <section className="hero">
      <div><div className="eyebrow"><Sparkles size={13} /> Four accounts · one view</div><h1>Usage, without<br /><span>the tab shuffle.</span></h1><p>Two Codex accounts, Claude, and Agy—checked locally.</p></div>
      <div className="hero-actions"><div><strong>{live}/{accounts.length || 4}</strong><span>reporting now</span></div><button onClick={refresh} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} />{loading ? 'Checking…' : 'Refresh all'}</button></div>
    </section>
    {error ? <div className="error"><ShieldCheck size={18} /><span><strong>Monitor unavailable</strong>{error}</span></div> : <section className="account-grid">{accounts.map(account => <AccountCard account={account} key={account.id} />)}</section>}
    <footer><span>Auto-refreshes every minute</span><span>Edit accounts.json to point at a second Codex home</span></footer>
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
