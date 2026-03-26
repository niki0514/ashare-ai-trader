type MetricCardProps = {
  label: string;
  value: string;
  accent?: number;
};

export function MetricCard({ label, value, accent }: MetricCardProps) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong className={accent === undefined ? "" : accent >= 0 ? "up" : "down"}>{value}</strong>
    </article>
  );
}
