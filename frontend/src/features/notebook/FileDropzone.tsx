import clsx from "clsx";
import { useRef, useState } from "react";

interface Props {
  label: string;
  accept?: string;
  onFile: (file: File) => void;
  disabled?: boolean;
}

/** Drag & drop area with a hidden file input fallback (keyboard accessible). */
export function FileDropzone({ label, accept, onFile, disabled = false }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      role="button"
      tabIndex={0}
      aria-disabled={disabled}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !disabled && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const file = e.dataTransfer.files[0];
        if (file && !disabled) onFile(file);
      }}
      className={clsx(
        "flex cursor-pointer items-center justify-center rounded-md border border-dashed px-3 py-4 text-xs text-ink-muted",
        over ? "border-brand bg-brand-soft" : "border-border hover:bg-subtle",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      {label}
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        data-testid="file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
