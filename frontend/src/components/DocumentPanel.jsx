import { X, FileText, Trash2 } from "lucide-react";
import { useApp } from "../store";
import UploadDropzone from "./UploadDropzone";
import { SecondaryButton } from "./Button";

export default function DocumentPanel({ onClose }) {
  const { documentNames, currentDocument, setCurrentDocument, upload, uploading, uploadError, uploadNotice, removeCurrentDocument } =
    useApp();

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-ink/40 px-4 py-10 overflow-y-auto" onClick={onClose}>
      <div
        className="relative w-full max-w-xl bg-bg border-2 border-ink rounded-lg shadow-card p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-heading text-2xl font-extrabold">Documents</h2>
          <button
            className="p-1.5 rounded-sm border-2 border-ink hover:bg-amber tactile"
            onClick={onClose}
            aria-label="Close document manager"
          >
            <X size={18} strokeWidth={2.5} />
          </button>
        </div>

        <UploadDropzone
          uploading={uploading}
          error={uploadError}
          notice={uploadNotice}
          onFile={async (file) => {
            try {
              await upload(file);
            } catch {
              /* uploadError is already surfaced in the dropzone */
            }
          }}
        />

        {documentNames.length > 0 && (
          <div className="mt-6">
            <h3 className="font-heading font-bold text-sm uppercase tracking-wide text-muted-fg mb-3">
              Your documents
            </h3>
            <ul className="flex flex-col gap-2">
              {documentNames.map((name) => {
                const active = name === currentDocument;
                return (
                  <li
                    key={name}
                    className={`flex items-center justify-between gap-3 px-4 py-3 rounded-md border-2 border-ink
                      ${active ? "bg-violet text-white" : "bg-white"}`}
                  >
                    <button
                      className="flex items-center gap-2 text-left flex-1 min-w-0 font-body font-semibold"
                      onClick={() => setCurrentDocument(name)}
                    >
                      <FileText size={18} strokeWidth={2.5} className="shrink-0" />
                      <span className="truncate">{name}</span>
                    </button>
                    {active && (
                      <button
                        className="p-1.5 rounded-sm border-2 border-white/70 hover:bg-pink hover:border-ink tactile shrink-0"
                        onClick={removeCurrentDocument}
                        aria-label={`Delete ${name}`}
                        title="Delete document"
                      >
                        <Trash2 size={16} strokeWidth={2.5} />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        <div className="mt-6 flex justify-end">
          <SecondaryButton onClick={onClose}>Done</SecondaryButton>
        </div>
      </div>
    </div>
  );
}
