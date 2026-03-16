/**
 * Auto-generated parameter input based on type definition.
 * Props:
 *   param — { name, label, type, default, min, max, step, options }
 *   value — current value
 *   onChange — (newValue) => void
 */
export default function ParamInput({ param, value, onChange }) {
  const { name, label, type = "number", min, max, step, options = [] } = param;

  if (type === "select") {
    return (
      <div>
        <label className="block text-[10px] text-gray-500 mb-1">{label || name}</label>
        <select
          value={value ?? param.default ?? ""}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs"
        >
          {options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </div>
    );
  }

  if (type === "boolean") {
    return (
      <div className="flex items-center gap-2">
        <label className="text-[10px] text-gray-500">{label || name}</label>
        <button
          onClick={() => onChange(!value)}
          className={`w-9 h-5 rounded-full relative transition-colors ${value ? "bg-emerald-600" : "bg-gray-700"}`}
        >
          <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${value ? "left-4" : "left-0.5"}`} />
        </button>
      </div>
    );
  }

  if (type === "range") {
    return (
      <div>
        <label className="block text-[10px] text-gray-500 mb-1">
          {label || name}: <span className="text-gray-300 font-mono">{value ?? param.default ?? min ?? 0}</span>
        </label>
        <input
          type="range"
          min={min ?? 0}
          max={max ?? 100}
          step={step ?? 1}
          value={value ?? param.default ?? min ?? 0}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full accent-emerald-500"
        />
      </div>
    );
  }

  // Default: number input
  return (
    <div>
      <label className="block text-[10px] text-gray-500 mb-1">{label || name}</label>
      <input
        type="number"
        min={min}
        max={max}
        step={step ?? (type === "float" ? 0.01 : 1)}
        value={value ?? param.default ?? ""}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono"
      />
    </div>
  );
}
