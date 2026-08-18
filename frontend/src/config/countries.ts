export interface CountryOption {
  code: string;
  name: string;
  // A couple of common cities to suggest, purely as tap-to-fill hints - the
  // city field itself is always a free text input, this isn't a closed list.
  cities: string[];
}

// Deliberately a short, curated list rather than every ISO country - this
// is a fitness-competition app, not a shipping-address form. Easy to extend
// later; the discover query itself accepts any country string.
export const COUNTRIES: CountryOption[] = [
  {
    code: "IN",
    name: "India",
    cities: ["Guwahati", "Mumbai", "Delhi", "Bengaluru"],
  },
  { code: "CN", name: "China", cities: ["Shanghai", "Beijing", "Shenzhen"] },
  { code: "SG", name: "Singapore", cities: ["Singapore"] },
  {
    code: "US",
    name: "United States",
    cities: ["New York", "Los Angeles", "Chicago"],
  },
  { code: "GB", name: "United Kingdom", cities: ["London", "Manchester"] },
  { code: "AE", name: "United Arab Emirates", cities: ["Dubai", "Abu Dhabi"] },
  { code: "AU", name: "Australia", cities: ["Sydney", "Melbourne"] },
  { code: "JP", name: "Japan", cities: ["Tokyo", "Osaka"] },
  { code: "DE", name: "Germany", cities: ["Berlin", "Munich"] },
  { code: "BR", name: "Brazil", cities: ["São Paulo", "Rio de Janeiro"] },
];
