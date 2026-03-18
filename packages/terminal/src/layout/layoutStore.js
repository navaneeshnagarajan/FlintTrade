const STORAGE_KEY = 'flinttrade:layouts'
const ACTIVE_KEY = 'flinttrade:activeLayout'

/**
 * Saves a layout to localStorage.
 * @param {string} id - Unique layout identifier.
 * @param {string} name - Display name for the layout.
 * @param {object} modelJson - FlexLayout model JSON produced by model.toJson().
 */
export function saveLayout(id, name, modelJson) {
  const layouts = getAllLayouts()
  layouts[id] = { id, name, model: modelJson, updatedAt: Date.now() }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts))
}

/**
 * Loads a layout model JSON by ID.
 * @param {string} id - Layout identifier.
 * @returns {object|null} FlexLayout model JSON, or null if not found.
 */
export function loadLayout(id) {
  const layouts = getAllLayouts()
  return layouts[id]?.model ?? null
}

/**
 * Returns all saved layouts as a plain object keyed by layout ID.
 * @returns {object} Map of layout ID to layout record.
 */
export function getAllLayouts() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
  } catch {
    return {}
  }
}

/**
 * Deletes a layout by ID from localStorage.
 * @param {string} id - Layout identifier to remove.
 */
export function deleteLayout(id) {
  const layouts = getAllLayouts()
  delete layouts[id]
  localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts))
}

/**
 * Renames an existing layout.
 * @param {string} id - Layout identifier.
 * @param {string} newName - New display name.
 */
export function renameLayout(id, newName) {
  const layouts = getAllLayouts()
  if (layouts[id]) {
    layouts[id].name = newName
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts))
  }
}

/**
 * Returns the currently active layout ID from localStorage.
 * @returns {string|null} Active layout ID, or null if not set.
 */
export function getActiveLayoutId() {
  return localStorage.getItem(ACTIVE_KEY) || null
}

/**
 * Persists the active layout ID to localStorage.
 * @param {string} id - Layout ID to mark as active.
 */
export function setActiveLayoutId(id) {
  localStorage.setItem(ACTIVE_KEY, id)
}

/**
 * Generates a unique layout ID using timestamp + random suffix.
 * @returns {string} Layout ID in the format LAY-<timestamp><random>.
 */
export function generateLayoutId() {
  return `LAY-${Date.now()}${Math.random().toString(36).slice(2, 8)}`
}
