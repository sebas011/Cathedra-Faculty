/* Tailwind CSS 3.x handoff configuration. This does not change the React build. */
module.exports = {
  content: { relative: true, files: ["./*.html"] },
  theme: {
    extend: {
      colors: {
        ink: "#182231", canvas: "#F6F7F4", cobalt: "#3154D9",
        "cobalt-soft": "#EDF1FF", apricot: "#F3B189", line: "#DDE2E8", "field-line": "#8492A4",
        muted: "#5D6A7B", danger: "#A92F3B", "danger-soft": "#FFF0F2",
        success: "#21674E", "success-soft": "#EDF7F1", warning: "#855710",
        "warning-soft": "#FFF6E5",
      },
      fontFamily: {
        sans: ["Aptos", "Segoe UI Variable", "Segoe UI", "system-ui", "sans-serif"],
        display: ["Georgia", "Times New Roman", "serif"],
      },
      boxShadow: { panel: "0 3px 14px rgb(24 34 49 / .025)" },
    },
  },
  plugins: [],
};
