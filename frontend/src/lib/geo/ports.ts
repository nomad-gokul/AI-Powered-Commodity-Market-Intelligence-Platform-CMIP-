/** Approximate coordinates for the trade hubs referenced across mock data
 * and map components — a single shared lookup so the market map's route
 * lines and the mock-data generators never drift out of sync. */
export const PORT_COORDINATES: Record<string, [number, number]> = {
  "Jebel Ali": [55.06, 25.01],
  Fujairah: [56.34, 25.11],
  Singapore: [103.82, 1.35],
  Rotterdam: [4.47, 51.92],
  "Ningbo-Zhoushan": [121.85, 29.87],
  Houston: [-95.27, 29.75],
  Sikka: [70.21, 22.43],
  "Richards Bay": [32.05, -28.78],
  Newcastle: [151.78, -32.93],
  Santos: [-46.33, -23.96],
  "Ras Laffan": [51.56, 25.91],
  Fangcheng: [108.35, 21.69],
};

export const PORT_NAMES = Object.keys(PORT_COORDINATES);

export const PORT_COUNTRY: Record<string, string> = {
  "Jebel Ali": "United Arab Emirates",
  Fujairah: "United Arab Emirates",
  Singapore: "Singapore",
  Rotterdam: "Netherlands",
  "Ningbo-Zhoushan": "China",
  Houston: "United States",
  Sikka: "India",
  "Richards Bay": "South Africa",
  Newcastle: "Australia",
  Santos: "Brazil",
  "Ras Laffan": "Qatar",
  Fangcheng: "China",
};
