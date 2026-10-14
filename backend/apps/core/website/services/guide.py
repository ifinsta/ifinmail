"""What each public page is for, who reads it, and what is at stake in what it says.

Written for the assistant, which drafts an organisation's own text for these pages: it needs to
know a page's job and its risks as well as its layout. The *standard* text and outline of a page
are not kept here (they would go stale); the assistant reads them from the rendered page. What is
kept here is judgement: purpose, audience, what must be true, what must not be invented.
"""

from __future__ import annotations

from dataclasses import dataclass

# The layout every Custom page has, whatever the standard page looks like.
CUSTOM_LAYOUT = (
    'A Custom page is one column: a large heading, one introduction paragraph under it, an '
    'optional single button, then the body. The body is Markdown (## and ### headings, - and 1. '
    'lists, **bold**, *italic*, [text](link), > quotes, --- rules, ``` code blocks); there are no '
    'images, tables, columns, cards or icons. The browser tab title and the search description '
    'are separate fields. The header, footer and navigation are the site\'s own and are not '
    'part of the text.'
)


@dataclass(frozen=True)
class PageGuide:
    purpose: str
    audience: str
    layout: str  # the standard page's structure, in one or two sentences
    stakes: str  # what goes wrong if the text is wrong
    risk: str  # 'low' | 'medium' | 'high'
    write: str  # what a good custom version contains
    typical: str  # what an organisation running this as its own service usually does
    body_words: str  # a sensible size


GUIDES: dict[str, PageGuide] = {
    'landing': PageGuide(
        purpose='The front door at the site\'s root: says what this mail service is and sends '
        'people to sign in or learn more. It is the first thing a visitor, a prospective '
        'user or a partner sees.',
        audience='Employees, customers or members who were told about the service; '
        'occasionally a partner\'s IT team.',
        layout='Hero (heading, introduction, two buttons, three short facts), an illustrative '
        'health panel, a six-card feature grid, a three-step "how it starts" sequence, a '
        'security teaser, a pricing teaser and a closing call to action.',
        stakes='First impression and trust. A vague or boastful page looks like a phishing '
        'page; claims about availability, security or support that are not true create '
        'liability. The standard text describes the open-source project (installing a server), '
        'which is wrong for people who only use an existing mailbox.',
        risk='medium',
        write='One sentence on what the service is and who it is for, why people use it, how '
        'to sign in (button to the sign-in page), and where to get help. Short.',
        typical='Custom, or Off (visitors go straight to sign-in).',
        body_words='80-200',
    ),
    'features': PageGuide(
        purpose='Explains what the service does, grouped by topic.',
        audience='Evaluators and people deciding whether to use or trust the service.',
        layout='Heading and introduction, then six two-column sections (mail, deliverability, '
        'DNS and certificates, protection, operations, plugins and assistant), each a lede on '
        'the left and a list of bold-lead items on the right, and a closing call to action.',
        stakes='Over-claiming. Every capability named must exist and be switched on for this '
        'organisation; promising calendars, retention or encryption that is not configured is '
        'a broken promise.',
        risk='medium',
        write='Only what is true of this deployment, as short grouped lists with a bold lead '
        'per item. Leave out operator-only features (DNS, certificates, plugins) unless the '
        'audience is technical.',
        typical='Custom for external-facing services; Off for internal ones.',
        body_words='150-400',
    ),
    'pricing': PageGuide(
        purpose='States what the service costs and what is included.',
        audience='Buyers, finance and procurement.',
        layout='Heading and introduction, then four short sections: included, what you bring, '
        'optional, support.',
        stakes='Commercial commitment. A price, plan, free tier or support promise written '
        'here is a public offer. The standard text says the software is free to run and you '
        'pay for a server, which is about the open-source project, not about this service.',
        risk='high',
        write='Only prices, plans and terms the organisation has given. Never invent figures, '
        'discounts, trials or service levels. If the service is internal or free to members, '
        'say so plainly.',
        typical='Off for internal services; Custom only with real commercial terms.',
        body_words='60-250',
    ),
    'security': PageGuide(
        purpose='Explains how mail and accounts are protected, and the limits.',
        audience='Security reviewers, auditors and cautious users.',
        layout='Heading and introduction, then sections: in transit, access, detection and '
        'records, your data and backups, the software, what is not claimed, reporting a '
        'vulnerability.',
        stakes='A false security claim is the most damaging text on the site: reviewers quote '
        'it and regulators read it. Certifications (ISO 27001, SOC 2), data locations, '
        'retention periods and encryption statements must be true and current.',
        risk='high',
        write='Only controls that exist (the standard page lists real ones: TLS, DKIM/SPF/DMARC, '
        'passkeys and second factors, audit trail, encrypted backups). Keep the honest "what we '
        'do not claim" section. Give a security contact address. Never add certifications or '
        'compliance statements the organisation did not state.',
        typical='Custom, keeping the factual protections and the contact; or Off.',
        body_words='150-400',
    ),
    'docs': PageGuide(
        purpose='Installation and operation guide for the platform.',
        audience='The person installing and running a server (an operator), not mailbox users.',
        layout='Heading and introduction, a table of contents, and long sections: requirements, '
        'install (a shell command), first setup, DNS and delegation, daily operation, backups, '
        'API, plugins and assistant, troubleshooting.',
        stakes='For an organisation that runs the platform for others this page is mostly '
        'irrelevant, and it exposes the install command and the project. Wrong replacement '
        'instructions (mail app settings, ports) lock people out of their mail.',
        risk='medium',
        write='If people need help: how to set up a mail app (IMAP server and port 993, '
        'SMTP port 587 or 465, username is the full address) using this server\'s real mail '
        'hostname, and who to ask. Nothing about installing the server.',
        typical='Off, or Custom as a short "set up your mail app" help page.',
        body_words='100-350',
    ),
    'changelog': PageGuide(
        purpose='Release notes of the platform software.',
        audience='Operators following the project.',
        layout='Heading and introduction, then one block per release with its notes, and a '
        'link to older releases.',
        stakes='It is the project\'s own history: it names the software and its versions, and '
        'can disclose when security fixes shipped. It says nothing about this organisation.',
        risk='low',
        write='Rarely worth writing. If the organisation wants a notice page ("what changed '
        'in our mail service"), write dated, plain entries it can stand behind.',
        typical='Off.',
        body_words='0-200',
    ),
    'download': PageGuide(
        purpose='Where people get the Android app (a build published in the console).',
        audience='People who want mail on an Android phone.',
        layout='Heading and introduction, then either the newest build with its version, size '
        'and checksum and install steps, or a notice that no build is published yet.',
        stakes='Installing an app from a page is a trust decision: the page must point only at '
        'the organisation\'s own signed build. The standard page shows the real build and '
        'checksum; custom text replaces that and can send people to the wrong place.',
        risk='high',
        write='Prefer keeping this page Standard: it is data-driven. If custom, say which '
        'app to install and where from, and nothing that is not verified.',
        typical='Standard if an Android build is published; otherwise Off.',
        body_words='40-150',
    ),
    'about': PageGuide(
        purpose='Says who runs the service and what it is.',
        audience='Anyone who wants to know who is behind it.',
        layout='Heading and introduction, then three sections: what it is, how we work, what '
        'it is not.',
        stakes='Identity. The standard page describes the open-source project and its '
        'maintainers, which would misrepresent the organisation. Statements about the '
        'company (founding, size, locations, customers) must be factual.',
        risk='medium',
        write='Who the organisation is in one or two sentences, what the mail service is for, '
        'who to contact. Use only facts the administrator gave.',
        typical='Custom or Off.',
        body_words='60-200',
    ),
    'contact': PageGuide(
        purpose='How to reach the people responsible, and how to report problems.',
        audience='Users needing help, and people reporting abuse or a security issue.',
        layout='Heading and introduction, then sections: questions and bugs, security reports '
        '(with a private reporting link), and read-first links to documentation.',
        stakes='A wrong or dead address means abuse and security reports go nowhere, and users '
        'cannot get help. The standard page points at the open-source project\'s issue tracker.',
        risk='high',
        write='A working help address or form, a security/abuse address, expected response '
        'times only if the organisation gave them. Use mailto: links.',
        typical='Custom. Do not leave it Off if people need support.',
        body_words='40-150',
    ),
    'terms': PageGuide(
        purpose='The terms of use between the operator and the people using the mail service.',
        audience='Users, and lawyers when there is a dispute.',
        layout='Heading with last-updated date, then sections: who the terms are with, your '
        'account, acceptable use, your mail and data, availability, suspension and ending, '
        'liability, the software, changes and contact.',
        stakes='Legal. Text here can bind the organisation or be read as a warranty it did not '
        'intend. The standard text is generic and describes an operator and a project; it is '
        'not legal advice and not tailored to any organisation. A wrong liability, availability '
        'or governing-law statement has real consequences.',
        risk='high',
        write='Use only terms the organisation supplied, or a plain-language skeleton clearly '
        'marked for legal review (acceptable use, account responsibility, data handling, '
        'contact). Never invent governing law, liability caps, SLAs or retention periods.',
        typical='Custom, written or approved by legal; the sign-in page links to it.',
        body_words='150-600',
    ),
    'privacy': PageGuide(
        purpose='What personal data is stored, why, and the people\'s rights.',
        audience='Users and regulators (GDPR and similar).',
        layout='Heading with last-updated date, then sections: who is responsible, what is '
        'stored, cookies and browser storage, what leaves this server, your choices, security, '
        'changes and contact.',
        stakes='Regulatory. Misstating what is collected, retention, or who the controller is '
        'is a compliance failure. The standard text describes what the software stores and '
        'says "the operator"; the organisation must name itself as the controller and add its '
        'own retention and contact details.',
        risk='high',
        write='Name the organisation as controller, list what is stored (mailbox contents, '
        'login and security logs) as the standard page does, add the organisation\'s retention '
        'and a data-protection contact. Do not claim data locations or processors you were '
        'not told.',
        typical='Custom, reviewed by whoever owns data protection; the sign-in page links to it.',
        body_words='150-500',
    ),
}


def for_page(key: str) -> PageGuide | None:
    return GUIDES.get(key)
