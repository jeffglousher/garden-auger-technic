//! Small editable XML tree. Qualified names and namespace declarations survive roundtrips.
use anyhow::{Context, Result};
use std::collections::BTreeMap;

#[derive(Clone, Debug)]
pub struct Node {
    pub name: String,
    pub attrs: BTreeMap<String, String>,
    pub children: Vec<Node>,
    text: Option<String>,
}

impl Node {
    pub fn new(name: &str, attrs: &[(&str, &str)]) -> Self {
        Self {
            name: name.into(),
            attrs: attrs
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
            children: vec![],
            text: None,
        }
    }
    pub fn local(&self) -> &str {
        self.name.rsplit(':').next().unwrap()
    }
    pub fn attr(&self, name: &str) -> Result<&str> {
        self.attrs
            .get(name)
            .map(String::as_str)
            .with_context(|| format!("{} lacks {name}", self.name))
    }
    pub fn is(&self, name: &str) -> bool {
        self.text.is_none() && self.local() == name
    }
    pub fn child_mut(&mut self, name: &str) -> Result<&mut Self> {
        let label = self.name.clone();
        self.children
            .iter_mut()
            .find(|n| n.is(name))
            .with_context(|| format!("{label} lacks {name}"))
    }
    pub fn metadata(&self) -> BTreeMap<String, String> {
        self.children
            .iter()
            .filter(|n| n.is("metadata"))
            .filter_map(|n| Some((n.attrs.get("key")?.clone(), n.attrs.get("value")?.clone())))
            .collect()
    }

    /// Use a default element namespace while preserving other element and attribute namespaces.
    pub fn use_default_namespace(&mut self, namespace: &str) -> Result<()> {
        fn visit(
            node: &mut Node,
            namespace: &str,
            inherited: &BTreeMap<String, String>,
            output_default: &str,
        ) -> Result<()> {
            if node.text.is_some() {
                return Ok(());
            }
            // Resolve names against the original scope before changing any declaration.
            let mut original = inherited.clone();
            for (key, value) in &node.attrs {
                if key == "xmlns" {
                    original.insert(String::new(), value.clone());
                } else if let Some(prefix) = key.strip_prefix("xmlns:") {
                    original.insert(prefix.into(), value.clone());
                }
            }
            let prefix = node.name.split_once(':').map_or("", |(prefix, _)| prefix);
            let uri = original
                .get(prefix)
                .with_context(|| format!("Unbound element prefix {prefix}"))?
                .clone();
            if uri == namespace {
                node.name = node.local().to_owned();
            }
            let mut output_default = node
                .attrs
                .get("xmlns")
                .map_or(output_default.to_owned(), Clone::clone);
            if !node.name.contains(':') && output_default != uri {
                node.attrs.insert("xmlns".into(), uri.clone());
                output_default = uri;
            }
            for child in &mut node.children {
                visit(child, namespace, &original, &output_default)?;
            }
            Ok(())
        }
        let scope = BTreeMap::from([
            (String::new(), String::new()),
            ("xml".into(), "http://www.w3.org/XML/1998/namespace".into()),
        ]);
        visit(self, namespace, &scope, "")
    }
}

pub fn parse(data: &[u8]) -> Result<Node> {
    let document = roxmltree::Document::parse(std::str::from_utf8(data)?)?;
    fn convert(n: roxmltree::Node<'_, '_>) -> Result<Node> {
        let qualified = |local: &str, uri: Option<&str>| match uri.and_then(|u| n.lookup_prefix(u))
        {
            Some(prefix) => format!("{prefix}:{local}"),
            None => local.to_owned(),
        };
        let mut attrs = BTreeMap::new();
        for attribute in n.attributes() {
            // Unlike elements, attributes never inherit the default namespace.
            let name = match attribute.namespace() {
                None => attribute.name().to_owned(),
                Some(uri) => {
                    let prefix = if uri == "http://www.w3.org/XML/1998/namespace" {
                        "xml"
                    } else {
                        n.namespaces()
                            .find(|ns| ns.uri() == uri && ns.name().is_some())
                            .and_then(|ns| ns.name())
                            .context("Namespaced XML attribute lacks a prefixed binding")?
                    };
                    format!("{prefix}:{}", attribute.name())
                }
            };
            attrs.insert(name, attribute.value().to_owned());
        }
        for ns in n.namespaces() {
            let inherited = n
                .parent_element()
                .and_then(|p| p.lookup_namespace_uri(ns.name()));
            if inherited != Some(ns.uri()) {
                attrs.insert(
                    ns.name()
                        .map_or_else(|| "xmlns".into(), |p| format!("xmlns:{p}")),
                    ns.uri().into(),
                );
            }
        }
        let mut children = Vec::new();
        for child in n.children() {
            if child.is_element() {
                children.push(convert(child)?);
            } else if child.is_text()
                && let Some(text) = child.text()
            {
                children.push(Node {
                    name: String::new(),
                    attrs: BTreeMap::new(),
                    children: vec![],
                    text: Some(text.into()),
                });
            }
        }
        Ok(Node {
            name: qualified(n.tag_name().name(), n.tag_name().namespace()),
            attrs,
            children,
            text: None,
        })
    }
    convert(document.root_element())
}

pub fn encode(node: &Node) -> Vec<u8> {
    fn escaped(s: &str) -> String {
        s.replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
            .replace('\n', "&#10;")
            .replace('\r', "&#13;")
            .replace('\t', "&#9;")
    }
    fn write(node: &Node, out: &mut String) {
        if let Some(text) = &node.text {
            out.push_str(&escaped(text));
            return;
        }
        out.push('<');
        out.push_str(&node.name);
        for (key, value) in &node.attrs {
            out.push_str(&format!(" {key}=\"{}\"", escaped(value)));
        }
        if node.children.is_empty() {
            out.push_str("/>");
        } else {
            out.push('>');
            for child in &node.children {
                write(child, out);
            }
            out.push_str(&format!("</{}>", node.name));
        }
    }
    let mut output = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n".to_owned();
    write(node, &mut output);
    output.into_bytes()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn namespaced_attributes_and_escaped_settings_survive() -> Result<()> {
        let source = br#"<model xmlns="core" xmlns:p="production"><component p:path="/mesh&amp;x" p:UUID="abc" value="a&#10;b&quot;c"/></model>"#;
        let rebuilt = encode(&parse(source)?);
        let text = std::str::from_utf8(&rebuilt)?;
        let doc = roxmltree::Document::parse(text)?;
        let child = doc.root_element().first_element_child().unwrap();
        assert_eq!(child.attribute(("production", "path")), Some("/mesh&x"));
        assert_eq!(child.attribute("value"), Some("a\nb\"c"));
        assert_eq!(child.tag_name().namespace(), Some("core"));
        Ok(())
    }

    #[test]
    fn attributes_keep_namespace_when_uri_has_default_and_prefixed_bindings() -> Result<()> {
        for source in [
            r#"<model xmlns="production" xmlns:p="production"><component p:path="/mesh.model" p:UUID="abc" path="plain" xml:lang="en"/></model>"#,
            r#"<c:model xmlns:c="core" xmlns="production" xmlns:p="production"><c:component p:path="/mesh.model" p:UUID="abc" path="plain" xml:lang="en"/></c:model>"#,
        ] {
            let rebuilt = encode(&parse(source.as_bytes())?);
            let doc = roxmltree::Document::parse(std::str::from_utf8(&rebuilt)?)?;
            let component = doc.root_element().first_element_child().unwrap();
            assert_eq!(
                component.attribute(("production", "path")),
                Some("/mesh.model")
            );
            assert_eq!(component.attribute(("production", "UUID")), Some("abc"));
            assert_eq!(
                component
                    .attributes()
                    .find(|a| a.name() == "path" && a.namespace().is_none())
                    .map(|a| a.value()),
                Some("plain")
            );
            assert_eq!(
                component.attribute(("http://www.w3.org/XML/1998/namespace", "lang")),
                Some("en")
            );
        }
        Ok(())
    }

    #[test]
    fn canonical_default_namespace_preserves_nested_namespace_changes() -> Result<()> {
        let source = r#"<c:model xmlns:c="core" xmlns="production" xmlns:p="production" p:path="/mesh"><detail><c:component p:UUID="one"/><plain xmlns=""><c:component xml:lang="en"/></plain></detail></c:model>"#;
        let before = roxmltree::Document::parse(source)?;
        let mut model = parse(source.as_bytes())?;
        model.use_default_namespace("core")?;
        let rebuilt = encode(&model);
        let after = roxmltree::Document::parse(std::str::from_utf8(&rebuilt)?)?;
        for (a, b) in before
            .descendants()
            .filter(|n| n.is_element())
            .zip(after.descendants().filter(|n| n.is_element()))
        {
            assert_eq!(
                (a.tag_name().namespace(), a.tag_name().name()),
                (b.tag_name().namespace(), b.tag_name().name())
            );
            for attribute in a.attributes() {
                assert_eq!(
                    b.attributes()
                        .find(|v| v.name() == attribute.name()
                            && v.namespace() == attribute.namespace())
                        .map(|v| v.value()),
                    Some(attribute.value())
                );
            }
        }
        assert_eq!(
            after.root_element().lookup_namespace_uri(None),
            Some("core")
        );
        Ok(())
    }
}
