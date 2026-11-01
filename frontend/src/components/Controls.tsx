import { Settings, Image as ImageIcon, Play, FolderOpen } from 'lucide-react'

export default function Controls({
  inputDir, setInputDir,
  files, fetchFiles, browseDirectory,
  extension, setExtension,
  polarisX, setPolarisX,
  polarisY, setPolarisY,
  startJob
}: any) {
  return (
    <div className="lg:col-span-4 space-y-6">

      <section className="bg-zinc-900/50 rounded-2xl p-6 border border-zinc-800 shadow-[inset_0_1px_0_rgba(255,255,255,0.05),0_8px_20px_rgba(0,0,0,0.4)] backdrop-blur-xl">
        <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-4 flex items-center gap-2">
          <ImageIcon className="w-4 h-4" /> Source
        </h2>
        <div className="space-y-4">
          <div>
            <label className="block text-xs text-zinc-500 mb-1 ml-1">Input Directory</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={inputDir}
                onChange={e => setInputDir(e.target.value)}
                placeholder="Choose a folder or type a path"
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 shadow-[inset_0_2px_4px_rgba(0,0,0,0.3)] transition-all"
              />
              <button
                onClick={browseDirectory}
                title="Browse for a folder"
                className="px-3 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 hover:border-zinc-600 rounded-lg shadow-[inset_0_1px_1px_rgba(255,255,255,0.1)] transition-all active:scale-95 flex items-center"
              >
                <FolderOpen className="w-4 h-4" />
              </button>
              <button
                onClick={fetchFiles}
                disabled={files.length === 0 && !inputDir}
                className="px-3 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 hover:border-zinc-600 rounded-lg shadow-[inset_0_1px_1px_rgba(255,255,255,0.1)] transition-all active:scale-95"
              >
                Scan
              </button>
            </div>
          </div>
          {files.length > 0 && (
            <div className="text-xs text-blue-400 bg-blue-400/10 px-3 py-2 rounded-lg border border-blue-400/20">
              {files.length} images detected
            </div>
          )}
        </div>
      </section>

      <section className="bg-zinc-900/50 rounded-2xl p-6 border border-zinc-800 shadow-[inset_0_1px_0_rgba(255,255,255,0.05),0_8px_20px_rgba(0,0,0,0.4)] backdrop-blur-xl">
        <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-4 flex items-center gap-2">
          <Settings className="w-4 h-4" /> Parameters
        </h2>
        <div className="space-y-5">
          <div>
            <label className="block text-xs text-zinc-500 mb-1 ml-1 flex justify-between">
              <span>Trail Extension Factor</span>
              <span className="text-zinc-300">{extension}x</span>
            </label>
            <input
              type="range" min="1.0" max="5.0" step="0.1"
              value={extension} onChange={e => setExtension(Number(e.target.value))}
              className="w-full accent-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-zinc-500 mb-1 ml-1">Polaris X (Optional)</label>
              <input
                type="number" value={polarisX} onChange={e => setPolarisX(e.target.value === '' ? '' : Number(e.target.value))}
                placeholder="Auto"
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 shadow-[inset_0_2px_4px_rgba(0,0,0,0.3)] transition-all"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1 ml-1">Polaris Y (Optional)</label>
              <input
                type="number" value={polarisY} onChange={e => setPolarisY(e.target.value === '' ? '' : Number(e.target.value))}
                placeholder="Auto"
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 shadow-[inset_0_2px_4px_rgba(0,0,0,0.3)] transition-all"
              />
            </div>
          </div>
        </div>
      </section>

      <button
        onClick={startJob}
        disabled={files.length === 0}
        className="w-full relative overflow-hidden group disabled:opacity-50 disabled:cursor-not-allowed bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-xl py-3 px-4 shadow-[inset_0_1px_1px_rgba(255,255,255,0.3),0_4px_10px_rgba(37,99,235,0.3)] active:scale-95 transition-all flex items-center justify-center gap-2"
      >
        <div className="absolute inset-0 bg-gradient-to-b from-white/20 to-transparent pointer-events-none" />
        <Play className="w-4 h-4 fill-current" />
        Start Processing
      </button>

    </div>
  )
}
