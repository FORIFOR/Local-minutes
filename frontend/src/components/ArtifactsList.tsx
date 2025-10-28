type FileItem = { name: string; url: string; size?: string; ts?: string }

export default function ArtifactsList({ files = [] as FileItem[] }: { files?: FileItem[] }) {
  if (!files.length) return null
  return (
    <div className="card">
      <div className="font-semibold mb-2">生成物</div>
      <div className="divide-y divide-black/5 dark:divide-white/5">
        {files.map((f, i) => (
          <a key={i} href={f.url} className="flex items-center justify-between py-2 hover:underline">
            <div>{f.name}</div>
            <div className="text-xs text-[--muted]">{[f.size, f.ts].filter(Boolean).join(' / ')}</div>
          </a>
        ))}
      </div>
    </div>
  )
}
