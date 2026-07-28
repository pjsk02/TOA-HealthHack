# TOA Health Hack: DICOM Search

## Finding and Accessing the Scans Without Moving Them

Imagine a child undergoing treatment for a brain tumor. Every few months, the child has another MRI while the family waits to learn whether the tumor has grown, stayed stable, or responded to treatment. Researchers want to build tools that help specialists measure these changes more consistently, but doing that well requires examples from many children, scanners, hospitals, treatments, and stages of disease.

Pediatric brain tumors are uncommon, so no single hospital may have enough examples. The scans researchers need may already exist across a network of children's hospitals, but right now there is no good way to know and even less clarity on how to securely access them once found. Before researchers can train life-saving models, they need a safe way to find where data exists and a secure mechanism to access permitted scans without exposing sensitive patient health information.

## Where We Are Getting Stuck

Each hospital knows what data it holds. One may have hundreds of brain MRIs, another may have detailed treatment histories, and a third may have the rare cases needed to learn whether a model works reliably. Yet the images and medical records cannot simply be gathered in one place. Hospitals must protect patient privacy and comply with federal, state, contractual, and institutional restrictions.

As a result, researchers approach hospitals one at a time. They may spend months making contacts, seeking approvals, and describing a proposed study before they even learn whether enough suitable data exists, let alone getting authorization to view it.

We need a dependable way to ask the participating network: *Where might relevant data exist, how much is available, who is authorized to see it, and how can we securely retrieve it?*

## A Technical Starting Point

Most medical images in hospitals are stored and exchanged as DICOM objects containing image metadata tagged with attributes like scan type (MRI, CT), study descriptions, body region, acquisition settings, and diagnostic notes.

To give you a running start, we are providing the **Provider Node Boilerplate (`https://github.com/snellutla-rh/provider-node`)**. This repository comes pre-loaded with synthetic DICOM metadata and clinical records distributed across simulated hospital nodes. You can build your architecture directly on top of this foundation to simulate how individual hospital endpoints store and expose metadata.

## The Discovery and Access Problem

Describing data safely across a network is difficult, but granting access to it is even harder:

1. **Semantic Diversity:** Different hospitals use different terms for the same conditions. A search for "tumor" at Hospital A must intelligently map to "neoplasm" or "low-grade glioma" at Hospital B.
2. **Privacy vs. Discovery:** Even simple patient counts can disclose too much if a hospital reports having only one child with a rare condition. Search responses must protect sensitive cohorts through obfuscation or differential privacy.
3. **Identity and Role-Based Access Control:** Data access is strictly dependent on *who* the researcher is. An academic researcher with IRB approval might be granted access to Hospital A's imaging files, but blocked from Hospital B's data, while an unauthenticated user shouldn't see anything beyond aggregated metadata.
4. **Secure Data Retrieval:** Locating the data is only half the battle. Once identified, how does a researcher securely request and receive access to permitted medical records across network boundaries without centralizing patient PII?

## Two Ways to Search (and Access)

- **Shared Index:** Hospitals publish privacy-safe summaries of selected collections to a central, searchable manifest. This gives researchers a quick view across the network.
- **Distributed Search:** The central system forwards the researcher's query directly to participating hospital nodes. Each node evaluates the query against local databases and local access policies before returning an answer.

In both models, once matching data is discovered, the system must authenticate the researcher's credentials and execute a zero-trust retrieval or request workflow.

## The Challenge

How might independent healthcare providers make safe descriptions of their locally held medical imaging data discoverable *and* securely accessible through one unified, permissions-aware network?

A successful system will allow a researcher to query the entire network using natural language or DICOM parameters, aggregate the results safely, verify the researcher's identity and authorization, and grant secure access to permitted DICOM datasets according to local provider rules.

## A Suggested Scope for the Hack

To make this achievable in a single day, teams should leverage the provided starter code and focus on demonstrating end-to-end discovery and secure access across simulated endpoints.

### 1. Spin Up the Provider Network

Use the **Provider Node Boilerplate** to deploy simulated provider endpoints populated with synthetic DICOM metadata. Modify or extend these nodes to represent distinct hospital endpoints with individual access policies.

### 2. Build the Search & Semantic Engine

Construct a central query portal that accepts natural language or DICOM search parameters. Implement **semantic mapping** so that related diagnostic terms (e.g., "tumor" vs. "neoplasm") match across different provider nodes, whether through distributed querying or a shared index.

### 3. Implement Identity & Role-Based Access Control

Integrate an authentication layer that identifies the researcher (e.g., Dr. Jorgenson from Academic Hospital X vs. an external party). Ensure each hospital node evaluates the researcher's credentials before returning data access links or detailed patient records.

### 4. Demonstrate Secure Data Retrieval

Show the full lifecycle:

1. Dr. Jorgenson searches for pediatric brain MRI scans.
2. The network returns matching counts across hospitals while obfuscating sensitive/rare cohorts.
3. The system verifies Dr. Thorne's credentials and provides a secure pathway to retrieve or view the permitted DICOM metadata/images directly from the authorized hospital nodes.