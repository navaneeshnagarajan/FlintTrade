function readPackage(packageManifest) {
  if (packageManifest.name === "@glideapps/glide-data-grid" && packageManifest.version === "6.0.3") {
    // Glide Data Grid 6.0.3 works in the terminal on React 19, but its
    // published peer metadata still stops at React 18 and marked 4.
    packageManifest.peerDependencies = {
      ...packageManifest.peerDependencies,
      marked: "^4.0.10 || 17.x",
      react: "^16.12.0 || 17.x || 18.x || 19.x",
      "react-dom": "^16.12.0 || 17.x || 18.x || 19.x",
    };
  }

  return packageManifest;
}

module.exports = {
  hooks: {
    readPackage,
  },
};
