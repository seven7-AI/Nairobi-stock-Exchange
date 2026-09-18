import { useSearchParams } from "react-router-dom";
import { fmtDate } from "../../lib/format";

/** Bound to ?as_of=; lists the dates the store actually holds. */
export function AsOfSelector({ dates, current, param = "as_of" }: { dates: string[]; current: string; param?: string }) {
  const [params, setParams] = useSearchParams();
  const options = dates.includes(current) ? dates : [current, ...dates];
  return (
    <label className="controls small">
      as of
      <select
        value={current}
        aria-label="Result date"
        onChange={(e) => {
          const next = new URLSearchParams(params);
          if (e.target.value === dates[0]) next.delete(param);
          else next.set(param, e.target.value);
          setParams(next);
        }}
      >
        {options.map((d) => (
          <option key={d} value={d}>
            {fmtDate(d)}
            {d === dates[0] ? " (latest)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
