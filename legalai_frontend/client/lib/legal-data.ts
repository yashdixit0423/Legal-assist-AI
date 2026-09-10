export type StatuteSection = {
  id: string;
  number: string;
  act: string;
  shortAct: string;
  heading: string;
  asOf: string;
  text: string;
  explanation: string;
  amendment: string;
  related: string[];
};

export type Statute = {
  slug: string;
  title: string;
  shortTitle: string;
  year: string;
  jurisdiction: string;
  tier: string;
  sections: number;
  asOf: string;
  ministry: string;
  actNumber: string;
  longTitle: string;
  sourceUrl: string;
  repealed?: boolean;
  chapters: { label: string; sections: string[] }[];
};

export const sections: StatuteSection[] = [
  {
    id: "contract-27",
    number: "27",
    act: "Indian Contract Act, 1872",
    shortAct: "Contract Act, 1872",
    heading: "Agreement in restraint of trade, void",
    asOf: "31 March 2024",
    text: "Every agreement by which anyone is restrained from exercising a lawful profession, trade or business of any kind, is to that extent void.",
    explanation:
      "An agreement that stops someone from carrying on a lawful profession, trade or business is generally not enforceable to that extent. The section includes a narrow exception for the sale of goodwill, subject to stated limits.",
    amendment: "Text reflects amendments available in the indexed corpus as of 31 March 2024.",
    related: ["Contract Act, 1872 — S. 28", "Specific Relief Act, 1963 — S. 41"],
  },
  {
    id: "registration-17",
    number: "17",
    act: "The Registration Act, 1908",
    shortAct: "Registration Act, 1908",
    heading: "Documents of which registration is compulsory",
    asOf: "31 March 2024",
    text: "The following documents shall be registered, if the property to which they relate is situated in a district in which, and if they have been executed on or after the date on which, the provisions of this Part commence to apply...",
    explanation:
      "Section 17 identifies classes of instruments that must be registered, including certain instruments affecting rights in immovable property. The exact requirement depends on the document and the property involved.",
    amendment: "Text reflects amendments available in the indexed corpus as of 31 March 2024.",
    related: ["Registration Act, 1908 — S. 18", "Transfer of Property Act, 1882 — S. 54"],
  },
  {
    id: "arbitration-21",
    number: "21",
    act: "The Arbitration and Conciliation Act, 1996",
    shortAct: "Arbitration Act, 1996",
    heading: "Commencement of arbitral proceedings",
    asOf: "31 March 2024",
    text: "Unless otherwise agreed by the parties, the arbitral proceedings in respect of a particular dispute commence on the date on which a request for that dispute to be referred to arbitration is received by the respondent.",
    explanation:
      "Arbitral proceedings normally begin when the respondent receives a request to refer the particular dispute to arbitration, unless the parties have agreed on a different rule.",
    amendment: "Text reflects amendments available in the indexed corpus as of 31 March 2024.",
    related: ["Arbitration Act, 1996 — S. 11", "Arbitration Act, 1996 — S. 43"],
  },
  {
    id: "it-43",
    number: "43",
    act: "The Information Technology Act, 2000",
    shortAct: "Information Technology Act, 2000",
    heading: "Penalty and compensation for damage to computer, computer system, etc.",
    asOf: "31 March 2024",
    text: "If any person without permission of the owner or any other person who is incharge of a computer, computer system or computer network...",
    explanation:
      "This provision addresses specified acts that cause damage to a computer resource without the required permission. The indexed text is only a starting point for understanding the full provision.",
    amendment: "Text reflects amendments available in the indexed corpus as of 31 March 2024.",
    related: ["Information Technology Act, 2000 — S. 43A", "Information Technology Act, 2000 — S. 46"],
  },
];

export const statutes: Statute[] = [
  {
    slug: "contract-act-1872",
    title: "The Indian Contract Act, 1872",
    shortTitle: "Indian Contract Act",
    year: "1872",
    jurisdiction: "India",
    tier: "Central",
    sections: 266,
    asOf: "31 March 2024",
    ministry: "Ministry of Law and Justice · Legislative Department",
    actNumber: "Act No. 9 of 1872",
    longTitle: "An Act to define and amend certain parts of the law relating to contracts.",
    sourceUrl: "https://www.indiacode.nic.in/",
    chapters: [
      { label: "Part I · Of Contracts", sections: ["1", "2", "10", "23", "27", "28"] },
      { label: "Part II · Of Contracts relating to Sale of Goods", sections: ["76", "77", "78"] },
      { label: "Part III · Of Contracts of Agency", sections: ["182", "201", "202"] },
    ],
  },
  {
    slug: "registration-act-1908",
    title: "The Registration Act, 1908",
    shortTitle: "Registration Act",
    year: "1908",
    jurisdiction: "India",
    tier: "Central",
    sections: 91,
    asOf: "31 March 2024",
    ministry: "Ministry of Law and Justice · Legislative Department",
    actNumber: "Act No. 16 of 1908",
    longTitle: "An Act to consolidate the enactments relating to the registration of documents.",
    sourceUrl: "https://www.indiacode.nic.in/",
    chapters: [
      { label: "Part II · Of the Registration-establishment", sections: ["3", "5", "6"] },
      { label: "Part III · Of Registrable Documents", sections: ["17", "18", "21"] },
      { label: "Part IV · Of the Time of Presentation", sections: ["23", "25", "26"] },
    ],
  },
  {
    slug: "arbitration-act-1996",
    title: "The Arbitration and Conciliation Act, 1996",
    shortTitle: "Arbitration and Conciliation Act",
    year: "1996",
    jurisdiction: "India",
    tier: "Central",
    sections: 86,
    asOf: "31 March 2024",
    ministry: "Ministry of Law and Justice · Legislative Department",
    actNumber: "Act No. 26 of 1996",
    longTitle: "An Act to consolidate and amend the law relating to domestic arbitration, international commercial arbitration and enforcement of foreign arbitral awards.",
    sourceUrl: "https://www.indiacode.nic.in/",
    chapters: [
      { label: "Part I · Arbitration", sections: ["7", "11", "16", "21", "29A"] },
      { label: "Part II · Enforcement of Foreign Awards", sections: ["44", "47", "48"] },
    ],
  },
  {
    slug: "information-technology-act-2000",
    title: "The Information Technology Act, 2000",
    shortTitle: "Information Technology Act",
    year: "2000",
    jurisdiction: "India",
    tier: "Central",
    sections: 94,
    asOf: "31 March 2024",
    ministry: "Ministry of Electronics and Information Technology",
    actNumber: "Act No. 21 of 2000",
    longTitle: "An Act to provide legal recognition for transactions carried out by means of electronic data interchange and other means of electronic communication.",
    sourceUrl: "https://www.indiacode.nic.in/",
    repealed: true,
    chapters: [
      { label: "Chapter IX · Penalties and Adjudication", sections: ["43", "43A", "44", "46"] },
      { label: "Chapter XI · Offences", sections: ["65", "66", "67"] },
    ],
  },
];

export const citationLabel = (section: StatuteSection) =>
  `S. ${section.number} • ${section.shortAct}`;

export const sectionById = (id: string) => sections.find((section) => section.id === id) ?? sections[0];
