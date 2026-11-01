import { API_ORIGIN } from "../api";
import { motion, AnimatePresence } from 'framer-motion'
import { Terminal, Image as ImageIcon, CheckCircle } from 'lucide-react'

export default function MainStage({ jobState, files,   }: any) {

  // A helper to generate a preview URL based on the file paths found or job results
  const getPreviewUrl = (filepath: string) => {
    return `${API_ORIGIN}/api/images/preview?path=${encodeURIComponent(filepath)}`
  }

  return (
    <div className="lg:col-span-8 flex flex-col h-full">
      <section className="bg-zinc-900/40 rounded-2xl border border-zinc-800 shadow-xl overflow-hidden flex-1 relative flex flex-col min-h-[500px]">

        <div className="bg-zinc-950 border-b border-zinc-800 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-zinc-400 font-mono">
            <Terminal className="w-4 h-4" />
            <span>Pipeline Status</span>
          </div>
          {jobState && (
            <div className="flex items-center gap-2 text-xs px-2 py-1 rounded bg-zinc-900 border border-zinc-800 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full animate-pulse" style={{ backgroundColor: jobState.status === 'completed' ? '#4ade80' : jobState.status === 'failed' ? '#f87171' : '#60a5fa' }} />
              {jobState.status}
            </div>
          )}
        </div>

        <div className="flex-1 flex flex-col h-full relative">

          <AnimatePresence mode="wait">
            {!jobState ? (
              <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="text-zinc-600 text-center flex flex-col items-center justify-center h-full p-6">
                {files.length > 0 ? (
                  <div className="w-full h-full p-4 overflow-y-auto grid grid-cols-4 gap-2 content-start">
                     {files.slice(0, 12).map((f: string, i: number) => (
                       <div key={i} className="aspect-square bg-zinc-950 rounded border border-zinc-800 overflow-hidden relative group">
                          <img src={getPreviewUrl(f)} className="w-full h-full object-cover opacity-70 group-hover:opacity-100 transition-opacity" alt="preview" />
                       </div>
                     ))}
                     {files.length > 12 && (
                       <div className="aspect-square bg-zinc-900 rounded border border-zinc-800 flex items-center justify-center text-xs">
                         +{files.length - 12} more
                       </div>
                     )}
                  </div>
                ) : (
                  <>
                    <ImageIcon className="w-16 h-16 mx-auto mb-4 opacity-50" />
                    <p>Load images to view sequence</p>
                  </>
                )}
              </motion.div>
            ) : jobState.status === 'completed' ? (
              <motion.div key="done" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="flex flex-col h-full w-full">
                <div className="flex-1 p-4 flex flex-col items-center justify-center relative">
                   <img src={getPreviewUrl(jobState.result_path)} className="max-w-full max-h-full object-contain rounded-lg shadow-2xl border border-zinc-700" alt="Final Stacked Result" />
                </div>
                <div className="bg-zinc-950/80 p-4 border-t border-zinc-800 flex justify-between items-center">
                  <div>
                    <h3 className="text-sm font-bold text-green-400 flex items-center gap-2"><CheckCircle className="w-4 h-4" /> Render Complete</h3>
                    <p className="text-zinc-400 font-mono text-xs mt-1">{jobState.result_path}</p>
                  </div>
                  <a href={getPreviewUrl(jobState.result_path)} download className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-sm rounded border border-zinc-700 transition-colors">Download / Save</a>
                </div>
              </motion.div>
            ) : jobState.status === 'failed' ? (
              <motion.div key="error" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="text-red-400 max-w-lg text-center flex flex-col items-center justify-center h-full p-6 mx-auto">
                <h3 className="text-xl font-bold mb-2">Processing Failed</h3>
                <div className="bg-red-950/30 p-4 w-full rounded text-sm text-left border border-red-900/50 font-mono overflow-auto max-h-48 whitespace-pre-wrap break-words">
                  {jobState.error}
                </div>
              </motion.div>
            ) : (
              <motion.div key="running" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full h-full flex flex-col p-6 items-center justify-center space-y-8">

                <div className="relative w-64 h-64 flex items-center justify-center">
                   {/* Cool radar/scanning effect */}
                   <div className="absolute inset-0 border-2 border-blue-500/20 rounded-full animate-ping" style={{ animationDuration: '3s' }} />
                   <div className="absolute inset-4 border border-blue-400/30 rounded-full animate-spin-slow" />
                   <div className="text-4xl text-blue-400 font-light tabular-nums">
                     {Math.round((jobState.progress || 0) * 100)}%
                   </div>
                </div>

                <div className="w-full max-w-md space-y-4 text-center">
                  <div className="text-lg font-medium text-zinc-200">
                    {jobState.stage === 'preparation' ? 'Scanning & Validating' :
                     jobState.stage === 'pass1' ? 'Pass 1: Tracking & Centroiding' :
                     jobState.stage === 'pass2' ? 'Pass 2: Aligning & Blending' : 'Processing...'}
                  </div>

                  <div className="relative h-2 bg-zinc-950 rounded-full overflow-hidden shadow-[inset_0_1px_3px_rgba(0,0,0,0.5)] border border-zinc-800">
                    <motion.div
                      className="absolute left-0 top-0 bottom-0 bg-gradient-to-r from-blue-600 to-blue-400 shadow-[0_0_10px_rgba(59,130,246,0.5)]"
                      initial={{ width: 0 }}
                      animate={{ width: `${(jobState.progress || 0) * 100}%` }}
                      transition={{ duration: 0.3 }}
                    />
                  </div>

                  {jobState.current !== undefined && jobState.total !== undefined && (
                    <div className="text-zinc-500 font-mono text-xs flex justify-between">
                      <span>{jobState.status}</span>
                      <span>Frame {jobState.current} / {jobState.total}</span>
                    </div>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

        </div>
      </section>
    </div>
  )
}
