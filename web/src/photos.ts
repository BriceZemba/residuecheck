// Real photographs from Wikimedia Commons, served from web/public/photos (resized, WebP) and credited in the footer
// as their licences require.
export interface Photo {
  src: string
  alt: string
  author: string
  license: string
  licenseUrl: string
  page: string
}

export const PHOTOS = {
  harvest: {
    src: '/photos/souss-harvest.webp',
    alt: 'Orange harvest in an orchard of the Souss region, Morocco, with picking crates between the trees',
    author: 'Raoul Rives',
    license: 'CC BY-SA 4.0',
    licenseUrl: 'https://creativecommons.org/licenses/by-sa/4.0',
    page: 'https://commons.wikimedia.org/wiki/File:Oranges_(10).JPG',
  },
  tree: {
    src: '/photos/souss-tree.webp',
    alt: 'Orange tree heavy with fruit, Souss region, Morocco',
    author: 'Raoul Rives',
    license: 'CC BY-SA 4.0',
    licenseUrl: 'https://creativecommons.org/licenses/by-sa/4.0',
    page: 'https://commons.wikimedia.org/wiki/File:Orangers2_(Souss).JPG',
  },
  clementines: {
    src: '/photos/clementines.webp',
    alt: 'Clementines stacked close up',
    author: 'Lukas B',
    license: 'CC0',
    licenseUrl: 'https://creativecommons.org/publicdomain/zero/1.0/',
    page: 'https://commons.wikimedia.org/wiki/File:Clementine_Close_Up_(132208599).jpeg',
  },
  spraying: {
    src: '/photos/orchard-spraying.webp',
    alt: 'A farmer spraying an orchard from a tractor',
    author: 'Archives of Ontario, RG 16-276',
    license: 'OGL-ON',
    licenseUrl: 'https://www.ontario.ca/page/open-government-licence-ontario',
    page: 'https://commons.wikimedia.org/wiki/File:Farmer_spraying_his_orchard_(I0003223).jpg',
  },
} satisfies Record<string, Photo>
