#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeJsEnvironment {
    pub version: String,
    pub npm_version: String,
    pub node_path: String,
}

impl NodeJsEnvironment {
    pub fn lts() -> Self {
        Self {
            version: "v20.18.0".into(),
            npm_version: "10.8.2".into(),
            node_path: "/usr/bin/node".into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_nodejs_environment_aaa() {
        // Arrange & Act
        let env = NodeJsEnvironment::lts();
        // Assert
        assert!(env.version.starts_with("v20"));
        assert_eq!(env.node_path, "/usr/bin/node");
    }
}
