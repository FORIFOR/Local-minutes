"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/config";

type Props = { meetingId: string };

export default function SummaryCard({ meetingId }: Props) {
  const [text, setText] = useState<string>("");
  const [progress, setProgress] = useState<number>(0);
  const [streaming, setStreaming] = useState(false);
  const [autoFollow, setAutoFollow] = useState(true);
  const areaRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const DRAFT_KEY = `summary_draft:${meetingId}`;

  // 自動追従スクロール（最下部にいるときのみ）
  useEffect(() => {
    if (!areaRef.current || !autoFollow) return;
    areaRef.current.scrollTop = areaRef.current.scrollHeight;
  }, [text, autoFollow]);

  // 初期読み込み: サーバ保存済みの最新要約を取得。未保存の場合はローカルドラフトを復元。
  useEffect(() => {
    let aborted = false;
    (async () => {
      try {
        const res = await fetch(api(`/api/events/${meetingId}`), { cache: 'no-store' as any });
        if (!res.ok) throw new Error(String(res.status));
        const j = await res.json();
        const saved: string = j?.summary?.text_md || '';
        if (!aborted) {
          if (saved) {
            setText(saved);
            setProgress(100);
          } else {
            // 暫定: 部分生成のドラフトをローカルから復元（最小範囲、final保存後は削除）
            const draft = localStorage.getItem(DRAFT_KEY) || '';
            if (draft) {
              setText(draft);
              setProgress(Math.min(99, Math.max(0, Math.floor((draft.length % 100) || 50))));
            }
          }
        }
      } catch {
        // サーバ未到達時のみローカルドラフトにフォールバック
        if (!aborted) {
          const draft = localStorage.getItem(DRAFT_KEY) || '';
          if (draft) {
            setText(draft);
            setProgress(Math.min(99, Math.max(0, Math.floor((draft.length % 100) || 50))));
          }
        }
      }
    })();
    return () => { aborted = true; };
  }, [meetingId]);

  const start = () => {
    stop(); // 再入防止 & 二重ストリーム防止
    setText("");
    setProgress(0);
    setStreaming(true);

    const url = api(`/api/events/${meetingId}/summary/stream`);
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("message", (ev) => {
      try {
        const j = JSON.parse((ev as MessageEvent).data);
        if (j?.type === "partial") {
          // サーバは累積テキストを返すため置換
          if (typeof j.text === "string") setText(j.text);
          if (typeof j.progress === "number") setProgress(Math.max(0, Math.min(99, Math.floor(j.progress))));
          // 暫定ドラフト保存（final到達時に削除）。撤去計画: サーバ側partial保存導入時に削除。
          try { if (typeof j.text === 'string') localStorage.setItem(DRAFT_KEY, j.text); } catch {}
        } else if (j?.type === "final") {
          if (typeof j.text === "string") setText(j.text);
          setProgress(100);
          setStreaming(false);
          es.close();
          esRef.current = null;
          try { localStorage.removeItem(DRAFT_KEY); } catch {}
        }
      } catch {
        // 無視（フォーマット外）
      }
    });
    es.addEventListener("error", () => {
      setStreaming(false);
      es.close();
      esRef.current = null;
    });
  };

  const stop = () => {
    esRef.current?.close();
    esRef.current = null;
    setStreaming(false);
  };

  // アンマウント時にSSEを確実にクローズ
  useEffect(() => {
    return () => {
      try { esRef.current?.close(); } catch {}
      esRef.current = null;
    };
  }, []);

  const copy = async () => {
    try { await navigator.clipboard.writeText(text); } catch {}
  };

  const onScroll = () => {
    const el = areaRef.current;
    if (!el) return;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 16;
    setAutoFollow(atBottom);
  };

  return (
    <section className="relative">
      <header className="mb-2 flex items-center justify-between">
        <h2 className="text-lg font-semibold">要約</h2>
        <div className="flex gap-2">
          <button
            onClick={start}
            disabled={streaming}
            className="px-3 py-1.5 rounded-lg border border-zinc-300 hover:bg-zinc-50 disabled:opacity-50"
          >
            {text ? "再生成" : "生成"}
          </button>
          <button
            onClick={stop}
            disabled={!streaming}
            className="px-3 py-1.5 rounded-lg border border-zinc-300 hover:bg-zinc-50 disabled:opacity-50"
          >
            停止
          </button>
          <button
            onClick={copy}
            disabled={!text}
            className="px-3 py-1.5 rounded-lg border border-zinc-300 hover:bg-zinc-50 disabled:opacity-50"
          >
            コピー
          </button>
        </div>
      </header>

      {/* ラベル */}
      <div className="mb-1 text-xs text-zinc-500 flex gap-3">
        <span className="inline-flex items-center gap-1">
          <i className="h-2 w-2 rounded-full bg-amber-300 inline-block" />
          AI生成
        </span>
      </div>

      {/* 本文（AI出力エリア：色分け＆スクロール） */}
      <div
        ref={areaRef}
        aria-live="polite"
        onScroll={onScroll}
        className="bg-amber-50/60 border border-amber-200 rounded-xl p-4 max-h-[60vh] overflow-y-auto prose prose-zinc dark:prose-invert"
      >
        {text ? (
          <>
            <pre className="whitespace-pre-wrap">{text}</pre>
            {streaming && <span className="ml-1 animate-pulse">▍</span>}
          </>
        ) : (
          <p className="text-zinc-500">まだ要約はありません。「生成」を押してください。</p>
        )}
      </div>

      {/* フッタ：進捗 */}
      <footer className="mt-2 text-xs text-zinc-500 flex items-center gap-2 justify-end">
        {streaming ? (
          <>
            <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" className="opacity-25" />
              <path d="M4 12a8 8 0 0 1 8-8" stroke="currentColor" strokeWidth="3" className="opacity-75" />
            </svg>
            生成中… {progress}%
          </>
        ) : (
          text && <span>最終更新: {new Date().toLocaleString()}</span>
        )}
      </footer>
    </section>
  );
}
