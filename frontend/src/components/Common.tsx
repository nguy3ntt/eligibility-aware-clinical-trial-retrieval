export const words = (value: string) => value.replaceAll("_", " ");
export function ErrorPanel({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="error" role="alert">
      <strong>Unable to complete this step</strong>
      <p>{message}</p>
      <button onClick={retry}>Try again</button>
    </div>
  );
}
export function Loading({ label }: { label: string }) {
  return (
    <p className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </p>
  );
}
export function JsonEvidence({
  value,
  label = "Full source and version record",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="evidence">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{words(status)}</span>;
}
