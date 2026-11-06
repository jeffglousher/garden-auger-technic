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
}

pub fn parse(data: &[u8]) -> Result<Node> {
    let document = roxmltree::Document::parse(std::str::from_utf8(data)?)?;
    fn convert(n: roxmltree::Node<'_, '_>) -> Node {
        let qualified = |local: &str, uri: Option<&str>| match uri.and_then(|u| n.lookup_prefix(u))
        {
            Some(prefix) => format!("{prefix}:{local}"),
            None => local.to_owned(),
        };
        let mut attrs: BTreeMap<_, _> = n
            .attributes()
            .map(|a| (qualified(a.name(), a.namespace()), a.value().to_owned()))
            .collect();
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
        let children = n
            .children()
            .filter_map(|c| {
                if c.is_element() {
                    Some(convert(c))
                } else {
                    c.text().filter(|_| c.is_text()).map(|s| Node {
                        name: String::new(),
                        attrs: BTreeMap::new(),
                        children: vec![],
                        text: Some(s.into()),
                    })
                }
            })
            .collect();
        Node {
            name: qualified(n.tag_name().name(), n.tag_name().namespace()),
            attrs,
            children,
            text: None,
        }
    }
    Ok(convert(document.root_element()))
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
}
