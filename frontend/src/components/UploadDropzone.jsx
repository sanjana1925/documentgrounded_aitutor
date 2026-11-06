import { useRef, useState } from "react";
import { FileText, UploadCloud } from "lucide-react";
import { PrimaryButton } from "./Button";
import { DecoDots } from "./DecorativeShapes";

export default function UploadDropzone({ onFile, uploading, error, notice }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  function handleFiles(files) {
    const file = files?.[0];
    if (file && file.type === "application/pdf") {
      onFile(file);
    }
  }

  return (
    <div
      className={`relative rounded-lg border-2 border-dashed px-8 py-12 text-center bg-white transition-colors
        ${dragging ? "border-violet bg-violet/5" : "border-ink"}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        handleFiles(e.dataTransfer.files);
      }}
    >
      <DecoDots className="hidden sm:block" style={{ left: "6%", top: "12%" }} />
      <DecoDots className="hidden sm:block" style={{ right: "6%", bottom: "12%" }} />

      <div className="relative z-10 flex flex-col items-center gap-4">
        <div className="w-16 h-16 rounded-md bg-amber/20 border-2 border-ink grid place-items-center">
          <FileText size={30} strokeWidth={2.5} className="text-ink" />
        </div>
        <h3 className="font-heading text-xl font-extrabold">Upload your study PDF</h3>
        <p className="text-muted-fg text-sm">Drop your file here, or browse to select one.</p>

        <PrimaryButton icon={UploadCloud} disabled={uploading} onClick={() => inputRef.current?.click()}>
          {uploading ? "Indexing…" : "Upload Document"}
        </PrimaryButton>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        {error && <p className="text-pink font-semibold text-sm">{error}</p>}
        {notice && !error && <p className="text-muted-fg font-semibold text-sm max-w-md">{notice}</p>}
      </div>
    </div>
  );
}
