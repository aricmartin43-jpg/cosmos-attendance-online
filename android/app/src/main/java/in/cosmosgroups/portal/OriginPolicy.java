package in.cosmosgroups.portal;
import java.net.URI;
final class OriginPolicy {
    static final String HOME = "https://cosmos-ecosystem-staging.onrender.com/";
    static boolean trusted(String url) {
        try {
            URI uri = new URI(url);
            return "https".equalsIgnoreCase(uri.getScheme())
                && "cosmos-ecosystem-staging.onrender.com".equalsIgnoreCase(uri.getHost())
                && uri.getUserInfo() == null && (uri.getPort() == -1 || uri.getPort() == 443);
        } catch (Exception e) { return false; }
    }
}
